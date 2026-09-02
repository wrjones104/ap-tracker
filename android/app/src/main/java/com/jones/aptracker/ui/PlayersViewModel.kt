package com.jones.aptracker.ui

import android.app.Application
import android.util.Log
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.network.Player
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.TrackMode
import com.jones.aptracker.network.UpdateSlotsRequest
import com.jones.aptracker.repository.HistoryRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class PlayersViewModel(application: Application) : AndroidViewModel(application) {
    val allPlayers = mutableStateOf<List<Player>>(emptyList())
    val selections = mutableStateMapOf<Int, Boolean>()

    /**
     * Per-slot "play" vs "watch" for the currently checked slots. Only slots in
     * a Cheese-linked room ever diverge from [TrackMode.PLAY]; everywhere else
     * this stays at the default and the picker hides the control entirely.
     */
    val slotModes = mutableStateMapOf<Int, String>()

    val isLoading = mutableStateOf(true)
    val showSaveConfirmation = mutableStateOf(false)
    val searchQuery = mutableStateOf("")
    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage = _errorMessage.asStateFlow()
    private val repository: HistoryRepository
    private var initialTrackedSlots = setOf<Int>()
    init {
        val db = AppDatabase.getInstance(application)
        repository = HistoryRepository(
            RetrofitClient.instance,
            db.historyDao(),
            db.hintDao(),
            application
        )
    }
    val filteredPlayers by derivedStateOf {
        val query = searchQuery.value.trim()

        if (query.isBlank()) {
            allPlayers.value
        } else {
            allPlayers.value.filter { player ->
                val nameMatches = player.name?.contains(query, ignoreCase = true) == true
                val aliasMatches = player.alias?.contains(query, ignoreCase = true) == true
                val gameMatches = player.game?.contains(query, ignoreCase = true) == true
                nameMatches || aliasMatches || gameMatches
            }
        }
    }

    fun fetchPlayers(roomId: Int) {
        isLoading.value = true
        _errorMessage.value = null
        viewModelScope.launch {
            try {
                Log.d("SLOTS_DEBUG", "fetchPlayers starting for roomId=$roomId")
                val playerList = RetrofitClient.instance.getPlayersInRoom(roomId)
                Log.d("SLOTS_DEBUG", "Received playerList of size ${playerList.size} from server.")
                allPlayers.value = playerList
                selections.clear()
                slotModes.clear()
                val trackedSlots = mutableSetOf<Int>()
                playerList.forEach { player ->
                    selections[player.slot_id] = player.is_tracked
                    slotModes[player.slot_id] = resolveInitialMode(player)
                    if (player.is_tracked) {
                        trackedSlots.add(player.slot_id)
                        Log.d("SLOTS_DEBUG", "  Detected already tracked slot: id=${player.slot_id}, name=${player.name}")
                    }
                }
                initialTrackedSlots = trackedSlots
                Log.d("SLOTS_DEBUG", "initialTrackedSlots set to: $initialTrackedSlots")
            } catch (e: Exception) {
                Log.e("SLOTS_DEBUG", "Failed to load players: ${e.message}", e)
                _errorMessage.value = "Failed to load players: ${e.message}"
            } finally {
                isLoading.value = false
            }
        }
    }

    /**
     * The mode a slot should start in.
     *
     * Already-tracked slots keep whatever the server says. For an untracked
     * slot the answer comes from Cheese: a slot someone else holds can only be
     * watched, so the picker starts it there rather than offering a claim that
     * would collide and then be undone.
     */
    private fun resolveInitialMode(player: Player): String {
        player.track_mode?.let { return it }
        val claim = player.cheese_claim ?: return TrackMode.PLAY
        return if (claim.can_claim) TrackMode.PLAY else TrackMode.WATCH
    }

    /**
     * True when the claim state came from Cheese rather than being assumed. False
     * for a room that has not synced yet, where the slot may already be held by
     * someone else and nothing has looked.
     */
    fun isClaimKnown(player: Player): Boolean = player.cheese_claim?.is_known ?: true

    /**
     * True when Cheese already records this slot as the user's.
     *
     * The picker is a form: until it is saved, Playing is an intention, not a fact.
     * This is what separates "you hold this" from "you are about to ask for it",
     * which the caption had been conflating.
     */
    fun isClaimMine(player: Player): Boolean = player.cheese_claim?.is_mine == true

    /** True when this slot is claimed on Cheese by someone other than the user. */
    fun isClaimLocked(player: Player): Boolean {
        val claim = player.cheese_claim ?: return false
        return !claim.can_claim
    }

    /** The Playing/Watching control makes sense for any Cheese-connected user. */
    fun showsTrackMode(player: Player): Boolean = player.cheese_claim != null

    fun modeFor(player: Player): String =
        slotModes[player.slot_id] ?: resolveInitialMode(player)

    fun onPlayerSelectionChanged(playerId: Int, isSelected: Boolean) {
        Log.d("SLOTS_DEBUG", "onPlayerSelectionChanged: slotId=$playerId, isSelected=$isSelected")
        selections[playerId] = isSelected
    }

    fun onTrackModeChanged(player: Player, mode: String) {
        // A slot held by someone else can never be set to Playing; the server
        // would refuse the claim and bounce it straight back to Watching.
        if (mode == TrackMode.PLAY && isClaimLocked(player)) {
            _errorMessage.value = claimedByMessage(player)
            return
        }
        Log.d("SLOTS_DEBUG", "onTrackModeChanged: slotId=${player.slot_id}, mode=$mode")
        slotModes[player.slot_id] = mode
    }

    fun claimedByMessage(player: Player): String {
        val holder = player.cheese_claim?.claimed_by
        return if (holder.isNullOrBlank()) {
            "That slot is claimed by someone else on Cheese Tracker. You can still watch it."
        } else {
            "That slot is claimed by $holder on Cheese Tracker. You can still watch it."
        }
    }

    fun saveSelections(roomId: Int) {
        viewModelScope.launch {
            isLoading.value = true
            _errorMessage.value = null
            try {
                val newTrackedSlots = selections.filter { it.value }.keys.toSet()
                val slotsToPrune = initialTrackedSlots - newTrackedSlots

                Log.d("SLOTS_DEBUG", "saveSelections starting for roomId=$roomId:")
                Log.d("SLOTS_DEBUG", "  initialTrackedSlots=$initialTrackedSlots")
                Log.d("SLOTS_DEBUG", "  selectionsMap=${selections.toMap()}")
                Log.d("SLOTS_DEBUG", "  newTrackedSlots=$newTrackedSlots")
                Log.d("SLOTS_DEBUG", "  slotsToPrune=$slotsToPrune")

                if (slotsToPrune.isNotEmpty()) {
                    Log.d("SLOTS_DEBUG", "  PRUNING slots locally: $slotsToPrune")
                    repository.pruneSlotData(roomId, slotsToPrune)
                } else {
                    Log.d("SLOTS_DEBUG", "  No slots to prune locally.")
                }

                // Only send modes for slots that can actually have one. Without a
                // Cheese key there is nothing to claim, so sending "play" for every
                // slot would just be noise on the wire. A room that is not linked
                // yet still gets modes: the user's choice has to reach the server
                // before the link catch-up runs.
                val modesToSend = newTrackedSlots
                    .filter { slotId -> allPlayers.value.any { it.slot_id == slotId && it.cheese_claim != null } }
                    .associate { slotId ->
                        slotId.toString() to (slotModes[slotId] ?: TrackMode.PLAY)
                    }

                val request = UpdateSlotsRequest(
                    tracked_slot_ids = newTrackedSlots.toList(),
                    slot_modes = modesToSend.ifEmpty { null }
                )
                Log.d("SLOTS_DEBUG", "  Sending updateTrackedSlots to server: $newTrackedSlots modes=$modesToSend")
                RetrofitClient.instance.updateTrackedSlots(roomId, request)
                showSaveConfirmation.value = true

                initialTrackedSlots = newTrackedSlots
                Log.d("SLOTS_DEBUG", "saveSelections successfully completed. initialTrackedSlots updated to $initialTrackedSlots")

            } catch (e: Exception) {
                Log.e("SLOTS_DEBUG", "Failed to save selections: ${e.message}", e)
                _errorMessage.value = "Failed to save selections."
            } finally {
                isLoading.value = false
            }
        }
    }

    fun isPlayerChecked(player: Player): Boolean {
        return selections[player.slot_id] ?: false
    }

    fun onSearchQueryChanged(query: String) {
        searchQuery.value = query
    }

    fun clearErrorMessage() {
        _errorMessage.value = null
    }
}