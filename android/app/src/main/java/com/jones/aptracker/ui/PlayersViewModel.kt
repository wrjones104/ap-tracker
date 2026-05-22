package com.jones.aptracker.ui

import android.app.Application
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
            db.hintDao()
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
                val playerList = RetrofitClient.instance.getPlayersInRoom(roomId)
                android.util.Log.d("PlayersViewModel", "fetchPlayers room=$roomId: ${playerList.size} players")
                playerList.forEach { p ->
                    android.util.Log.d("PlayersViewModel", "  slot_id=${p.slot_id}, name=${p.name}, is_tracked=${p.is_tracked}")
                }
                allPlayers.value = playerList
                selections.clear()
                val trackedSlots = mutableSetOf<Int>()
                playerList.forEach { player ->
                    selections[player.slot_id] = player.is_tracked
                    if (player.is_tracked) {
                        trackedSlots.add(player.slot_id)
                    }
                }
                initialTrackedSlots = trackedSlots
                android.util.Log.d("PlayersViewModel", "initialTrackedSlots=$initialTrackedSlots")
            } catch (e: Exception) {
                _errorMessage.value = "Failed to load players: ${e.message}"
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
            isLoading.value = true
            _errorMessage.value = null
            try {
                val newTrackedSlots = selections.filter { it.value }.keys.toSet()
                val slotsToPrune = initialTrackedSlots - newTrackedSlots
                android.util.Log.d("PlayersViewModel", "saveSelections room=$roomId: newTrackedSlots=$newTrackedSlots, initialTrackedSlots=$initialTrackedSlots, slotsToPrune=$slotsToPrune")

                if (slotsToPrune.isNotEmpty()) {
                    repository.pruneSlotData(roomId, slotsToPrune)
                }

                val request = UpdateSlotsRequest(tracked_slot_ids = newTrackedSlots.toList())
                android.util.Log.d("PlayersViewModel", "Sending to server: tracked_slot_ids=${newTrackedSlots.toList()}")
                RetrofitClient.instance.updateTrackedSlots(roomId, request)
                showSaveConfirmation.value = true

                initialTrackedSlots = newTrackedSlots

            } catch (e: Exception) {
                _errorMessage.value = "Failed to save selections."
                e.printStackTrace()
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