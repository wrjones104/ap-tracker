package com.jones.aptracker.ui

import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf // <-- Keep this for now for UI interaction
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.network.Player
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.UpdateSlotsRequest
import kotlinx.coroutines.launch
import android.util.Log // <-- Import Log

class PlayersViewModel : ViewModel() {
    // Holds the full list fetched from the API/DB
    val allPlayers = mutableStateOf<List<Player>>(emptyList())
    // Holds the *current* UI state of checkboxes before saving
    val checkboxStates = mutableStateMapOf<Int, Boolean>() // Renamed for clarity

    val isLoading = mutableStateOf(true)
    val showSaveConfirmation = mutableStateOf(false)
    val searchQuery = mutableStateOf("")
    val errorMessage = mutableStateOf<String?>(null)

    val filteredPlayers by derivedStateOf {
        if (searchQuery.value.isBlank()) {
            allPlayers.value
        } else {
            allPlayers.value.filter { player ->
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
                // Fetch from backend - this includes the *actual* is_tracked status
                val playerList = RetrofitClient.instance.getPlayersInRoom(roomId)
                allPlayers.value = playerList
                // Initialize checkboxStates based on the fetched data
                checkboxStates.clear()
                playerList.forEach { player ->
                    checkboxStates[player.slot_id] = player.is_tracked
                }
                Log.d("PlayersViewModel", "Fetched ${playerList.size} players. Initial states: $checkboxStates") // <-- Add Logging
            } catch (e: Exception) {
                errorMessage.value = "Failed to load players: ${e.message}"
                Log.e("PlayersViewModel", "Error fetching players", e) // <-- Add Logging
            } finally {
                isLoading.value = false
            }
        }
    }

    // Called when a checkbox is clicked in the UI
    fun onPlayerSelectionChanged(playerId: Int, isSelected: Boolean) {
        checkboxStates[playerId] = isSelected
        Log.d("PlayersViewModel", "Checkbox changed: Slot $playerId is now selected: $isSelected") // <-- Add Logging
    }

    // Called when the "Save" button is clicked
    fun saveSelections(roomId: Int) {
        isLoading.value = true // Show loading indicator during save
        errorMessage.value = null
        viewModelScope.launch {
            try {
                // Get IDs of players currently checked in the UI
                val selectedIds = checkboxStates.filter { it.value }.keys.toList()
                Log.d("PlayersViewModel", "Saving selections for Room $roomId. Selected IDs: $selectedIds") // <-- Add Logging
                val request = UpdateSlotsRequest(tracked_slot_ids = selectedIds)
                val response = RetrofitClient.instance.updateTrackedSlots(roomId, request) // Call the API

                if (response.isSuccessful) {
                    Log.d("PlayersViewModel", "Save successful. Updating local player states.") // <-- Add Logging
                    // --- IMPORTANT: Update the underlying 'allPlayers' list ---
                    // This makes the UI reflect the *saved* state immediately after saving.
                    val updatedPlayers = allPlayers.value.map { player ->
                        player.copy(is_tracked = selectedIds.contains(player.slot_id))
                    }
                    allPlayers.value = updatedPlayers
                    // --- End Update ---
                    showSaveConfirmation.value = true // Show the snackbar
                } else {
                    errorMessage.value = "Failed to save: ${response.errorBody()?.string()}"
                    Log.e("PlayersViewModel", "Save failed: ${response.code()} - ${response.errorBody()?.string()}") // <-- Add Logging
                }

            } catch (e: Exception) {
                errorMessage.value = "Failed to save selections: ${e.message}"
                Log.e("PlayersViewModel", "Error saving selections", e) // <-- Add Logging
            } finally {
                isLoading.value = false // Hide loading indicator
            }
        }
    }

    // This function now reads directly from the UI state map
    fun isPlayerChecked(player: Player): Boolean {
        return checkboxStates[player.slot_id] ?: false // Default to false if not found (shouldn't happen)
    }

    fun onSearchQueryChanged(query: String) {
        searchQuery.value = query
    }
}