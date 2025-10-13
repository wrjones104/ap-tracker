package com.jones.aptracker.ui

import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.network.Player
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.UpdateSlotsRequest
import kotlinx.coroutines.launch

class PlayersViewModel : ViewModel() {
    val allPlayers = mutableStateOf<List<Player>>(emptyList())
    val selections = mutableStateMapOf<Int, Boolean>()

    val isLoading = mutableStateOf(true)
    val showSaveConfirmation = mutableStateOf(false)
    val searchQuery = mutableStateOf("")
    val errorMessage = mutableStateOf<String?>(null)

    val filteredPlayers by derivedStateOf {
        if (searchQuery.value.isBlank()) {
            allPlayers.value
        } else {
            allPlayers.value.filter { player ->
                // **THE FIX**: Safely check for nulls before filtering
                (player.name?.contains(searchQuery.value, ignoreCase = true) ?: false) ||
                        (player.game?.contains(searchQuery.value, ignoreCase = true) ?: false)
            }
        }
    }

    fun fetchPlayers(roomId: Int) {
        isLoading.value = true
        errorMessage.value = null
        viewModelScope.launch {
            try {
                val playerList = RetrofitClient.instance.getPlayersInRoom(roomId)
                allPlayers.value = playerList
                selections.clear()
                playerList.forEach { player ->
                    selections[player.slot_id] = player.is_tracked
                }
            } catch (e: Exception) {
                errorMessage.value = "Failed to load players: ${e.message}"
                e.printStackTrace()
            } finally {
                isLoading.value = false
            }
        }
    }

    fun onPlayerSelectionChanged(playerId: Int, isSelected: Boolean) {
        selections[playerId] = isSelected
    }

    fun saveSelections(roomId: Int) {
        viewModelScope.launch {
            try {
                val selectedIds = selections.filter { it.value }.keys.toList()
                val request = UpdateSlotsRequest(tracked_slot_ids = selectedIds)
                RetrofitClient.instance.updateTrackedSlots(roomId, request)
                showSaveConfirmation.value = true
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }
    }

    fun isPlayerChecked(player: Player): Boolean {
        return selections[player.slot_id] ?: false
    }

    fun onSearchQueryChanged(query: String) {
        searchQuery.value = query
    }
}