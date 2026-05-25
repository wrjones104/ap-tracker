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
import com.jones.aptracker.network.UpdateSlotsRequest
import com.jones.aptracker.repository.HistoryRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class PlayersViewModel(application: Application) : AndroidViewModel(application) {
    val allPlayers = mutableStateOf<List<Player>>(emptyList())
    val selections = mutableStateMapOf<Int, Boolean>()

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
                val trackedSlots = mutableSetOf<Int>()
                playerList.forEach { player ->
                    selections[player.slot_id] = player.is_tracked
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

    fun onPlayerSelectionChanged(playerId: Int, isSelected: Boolean) {
        Log.d("SLOTS_DEBUG", "onPlayerSelectionChanged: slotId=$playerId, isSelected=$isSelected")
        selections[playerId] = isSelected
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

                val request = UpdateSlotsRequest(tracked_slot_ids = newTrackedSlots.toList())
                Log.d("SLOTS_DEBUG", "  Sending updateTrackedSlots to server: $newTrackedSlots")
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