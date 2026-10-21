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
import kotlinx.coroutines.CancellationException
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

    /**
     * "My slots": only the slots this user tracks (#438), so a big async does not
     * mean scrolling hundreds of rows to find your own. See [filterPlayers].
     */
    val showOnlyTracked = mutableStateOf(false)
    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage = _errorMessage.asStateFlow()
    private val repository: HistoryRepository
    private var initialTrackedSlots = setOf<Int>()
    /** [slotModes] as loaded, so a save sends only the modes changed here (#477). */
    private var initialSlotModes = mapOf<Int, String>()
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
        filterPlayers(allPlayers.value, searchQuery.value, showOnlyTracked.value, selections)
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
                initialSlotModes = slotModes.toMap()
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

    /**
     * Saves what changed in the picker, not the picker's whole snapshot (#477).
     *
     * `PUT rooms/{id}/slots` replaces the tracked set, and the picker's snapshot is as old as the
     * screen. Sent as it stood, it untracked a slot another device had tracked since (releasing
     * its Cheese claim) and re-tracked one another device had dropped (re-claiming it). So the
     * set is read fresh from `users/me/tracked-slots` right before the PUT, as
     * [UserViewModel.stopTrackingSlot] does, and only the edits made here are applied to it; see
     * [mergeSlotSelection]. A save that cannot read the fresh set is not sent.
     */
    fun saveSelections(roomId: Int) {
        viewModelScope.launch {
            isLoading.value = true
            _errorMessage.value = null
            try {
                val selected = selections.filter { it.value }.keys.toSet()
                val current = RetrofitClient.instance.getUserTrackedSlots()
                    .find { it.room_db_id == roomId }
                    ?.tracked_slots
                    ?.map { it.slot_id }
                    ?.toSet()
                    .orEmpty()

                // Only slots that can have a mode get one. Without a Cheese key there is
                // nothing to claim. A room that is not linked yet still gets modes: the
                // user's choice has to reach the server before the link catch-up runs.
                val modeCapable = allPlayers.value.filter { it.cheese_claim != null }.map { it.slot_id }.toSet()
                val save = mergeSlotSelection(
                    loaded = initialTrackedSlots,
                    selected = selected,
                    current = current,
                    loadedModes = initialSlotModes,
                    chosenModes = slotModes.toMap(),
                    modeCapable = modeCapable
                )

                Log.d("SLOTS_DEBUG", "saveSelections roomId=$roomId loaded=$initialTrackedSlots selected=$selected current=$current")
                Log.d("SLOTS_DEBUG", "  sending tracked=${save.trackedSlotIds} modes=${save.modes} removed=${save.removed}")

                val response = RetrofitClient.instance.updateTrackedSlots(
                    roomId,
                    UpdateSlotsRequest(
                        tracked_slot_ids = save.trackedSlotIds.toList(),
                        slot_modes = save.modes.mapKeys { it.key.toString() }.ifEmpty { null }
                    )
                )
                if (!response.isSuccessful) {
                    _errorMessage.value = "Failed to save selections."
                    return@launch
                }

                // Local history goes only for the slots unticked here, and only once the
                // server has agreed, the same order as Stop tracking.
                if (save.removed.isNotEmpty()) {
                    repository.pruneSlotData(roomId, save.removed)
                }
                showSaveConfirmation.value = true

                initialTrackedSlots = save.trackedSlotIds
                initialSlotModes = slotModes.toMap()
            } catch (e: CancellationException) {
                throw e
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

/**
 * The picker's visible rows: the search, and "My slots" when it is on.
 *
 * "My slots" keeps a slot the server says is tracked even after it is unticked, so a
 * mistaken untick can be undone before saving, and adds a slot ticked here but not yet
 * saved, so the selection can be reviewed. Kept out of the ViewModel so it can be tested
 * without one.
 */
internal fun filterPlayers(
    players: List<Player>,
    query: String,
    onlyTracked: Boolean,
    selections: Map<Int, Boolean>
): List<Player> {
    val pool = if (onlyTracked) {
        players.filter { it.is_tracked || selections[it.slot_id] == true }
    } else {
        players
    }
    val q = query.trim()
    if (q.isBlank()) return pool
    return pool.filter { player ->
        val nameMatches = player.name?.contains(q, ignoreCase = true) == true
        val aliasMatches = player.alias?.contains(q, ignoreCase = true) == true
        val gameMatches = player.game?.contains(q, ignoreCase = true) == true
        nameMatches || aliasMatches || gameMatches
    }
}

/** What a Manage Slots save sends, and which slots it untracked (for the local cleanup). */
internal data class SlotSelectionSave(
    val trackedSlotIds: Set<Int>,
    val modes: Map<Int, String>,
    val removed: Set<Int>
)

/**
 * The picker's edits applied to the tracked set as it is now, rather than as it was when the
 * picker loaded (#477).
 *
 * Slots ticked here are added and slots unticked here are removed. Every other slot keeps
 * whatever [current] says, so a slot another device tracked or dropped meanwhile stays that way.
 *
 * Modes go only for slots added here and slots whose mode was changed here. The server keeps
 * a slot's mode when the request leaves it out, so a mode set on another device survives too.
 * A slot added without a mode would default to Playing, so an added slot always sends one.
 * Kept out of the ViewModel so it can be tested without one.
 */
internal fun mergeSlotSelection(
    loaded: Set<Int>,
    selected: Set<Int>,
    current: Set<Int>,
    loadedModes: Map<Int, String>,
    chosenModes: Map<Int, String>,
    modeCapable: Set<Int>
): SlotSelectionSave {
    val added = selected - loaded
    val removed = loaded - selected
    val tracked = (current - removed) + added
    val modes = tracked
        .filter { it in modeCapable }
        .mapNotNull { slotId ->
            val chosen = chosenModes[slotId] ?: TrackMode.PLAY
            when {
                slotId in added -> slotId to chosen
                slotId in selected && chosenModes[slotId] != loadedModes[slotId] -> slotId to chosen
                else -> null
            }
        }
        .toMap()
    return SlotSelectionSave(tracked, modes, removed)
}
