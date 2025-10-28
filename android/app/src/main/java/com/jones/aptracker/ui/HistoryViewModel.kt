package com.jones.aptracker.ui

import android.app.Application
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.network.HintEntity // <-- Import HintEntity
import com.jones.aptracker.network.HistoryItem
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.repository.HistoryRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import android.util.Log // <-- Add Log import

class HistoryViewModel(application: Application) : AndroidViewModel(application) {

    private val repository: HistoryRepository
    private val _itemHistory = MutableStateFlow<List<HistoryItem>>(emptyList())
    val itemHistory: StateFlow<List<HistoryItem>> = _itemHistory

    // --- HINT STATE FLOWS ---
    private val _hintsForYou = MutableStateFlow<List<HintEntity>>(emptyList())
    val hintsForYou: StateFlow<List<HintEntity>> = _hintsForYou

    private val _hintsByYou = MutableStateFlow<List<HintEntity>>(emptyList())
    val hintsByYou: StateFlow<List<HintEntity>> = _hintsByYou
    // --- END HINT STATE FLOWS ---

    val searchQuery = mutableStateOf("")
    val isLoading = MutableStateFlow(true)
    val errorMessage = mutableStateOf<String?>(null)

    // --- NEW: State for the "Show Found" toggle ---
    private val _showFoundHints = MutableStateFlow(false)
    val showFoundHints: StateFlow<Boolean> = _showFoundHints
    // --- END NEW ---

    // Store current room ID for refresh logic
    private var currentRoomId: Int? = null

    init {
        val db = AppDatabase.getInstance(application)
        val historyDao = db.historyDao()
        val hintDao = db.hintDao()
        repository = HistoryRepository(RetrofitClient.instance, historyDao, hintDao)
    }

    /**
     * Main entry point to load all history for a room (or global).
     */
    fun loadHistoryFor(roomId: Int?) {
        currentRoomId = roomId // Store the room ID
        Log.d("HistoryViewModel", "Loading history for Room ID: ${roomId ?: "Global"}")
        isLoading.value = true
        errorMessage.value = null

        // Load Items
        viewModelScope.launch {
            val itemFlow = if (roomId != null) {
                repository.getHistoryForRoom(roomId)
            } else {
                repository.getGlobalHistory()
            }

            itemFlow
                .map { entities ->
                    entities.map { entity ->
                        HistoryItem( // Map Entity to UI Model
                            message = entity.message,
                            timestamp = entity.timestamp,
                            tracker_id = entity.tracker_id,
                            slot_id = entity.slot_id,
                            icon_name = entity.icon_name,
                            db_id = entity.roomId
                        )
                    }
                }
                .catch { e ->
                    errorMessage.value = "Failed to load item history: ${e.message}"
                    Log.e("HistoryViewModel", "Error loading item history", e)
                }
                .collect { historyList ->
                    _itemHistory.value = historyList
                    // We now wait for hints to finish before setting isLoading to false
                }
        }

        // Load Hints (using the new refactored function)
        loadHintHistory(setLoading = true) // Pass true to manage isLoading

        // Trigger background refresh for both
        refreshAllHistory()
    }

    /**
     * Loads *only* the hint history from the local DB, respecting the toggle.
     * This is called by loadHistoryFor and setShowFoundHints.
     */
    private fun loadHintHistory(setLoading: Boolean = false) {
        if (setLoading) {
            isLoading.value = true
        }

        viewModelScope.launch {
            val includeFound = _showFoundHints.value
            // --- LOGGING ---
            Log.d("HintToggleDebug", "VM: loadHintHistory called, includeFound = $includeFound")
            // ---

            val hintFlow = if (currentRoomId != null) {
                // Assumes repository method is updated to take the param
                repository.getHintsForRoom(currentRoomId!!, includeFound)
            } else {
                // Assumes repository method is updated to take the param
                repository.getGlobalHints(includeFound)
            }

            hintFlow
                .catch { e ->
                    errorMessage.value = "Failed to load hint history: ${e.message}"
                    Log.e("HistoryViewModel", "Error loading hint history", e)
                }
                .collect { (forYou, byYou) ->
                    // --- LOGGING ---
                    Log.d("HintToggleDebug", "VM: DAO returned ${forYou.size} 'forYou' hints, ${byYou.size} 'byYou' hints.")
                    // ---
                    _hintsForYou.value = forYou
                    _hintsByYou.value = byYou
                    if (setLoading) {
                        isLoading.value = false // Set loading false after hints load
                    }
                    Log.d("HistoryViewModel", "Loaded ${forYou.size} hints for you, ${byYou.size} hints by you.")
                }
        }
    }

    /**
     * Called by the UI when the "Show Found" toggle is changed.
     */
    fun setShowFoundHints(show: Boolean) {
        if (show == _showFoundHints.value) {
            // --- LOGGING ---
            Log.d("HintToggleDebug", "VM: setShowFoundHints called with same value: $show. Skipping.")
            // ---
            return // Don't reload if state is the same
        }
        // --- LOGGING ---
        Log.d("HintToggleDebug", "VM: setShowFoundHints NEW value: $show")
        // ---
        _showFoundHints.value = show

        // Re-load hint history from the repository (which reads from local DB)
        loadHintHistory(setLoading = false) // Don't show main loading spinner for a simple toggle

        // We also trigger a network refresh to get the correct filtered data
        refreshAllHistory()
    }

    /**
     * Triggers a network refresh for all data.
     */
    fun refreshAllHistory() {
        Log.d("HistoryViewModel", "Triggering background refresh for Room ID: ${currentRoomId ?: "Global"}")
        viewModelScope.launch {
            isLoading.value = true // Show loading indicator during refresh
            errorMessage.value = null
            try {
                // Refresh items
                repository.refreshItemHistory()
            } catch (e: Exception) {
                errorMessage.value = "Item Refresh failed: ${e.message}"
                Log.e("HistoryViewModel", "Error refreshing item history", e)
            }
            try {
                // --- MODIFIED: Pass the toggle state to the network refresh ---
                val includeFound = _showFoundHints.value
                // --- LOGGING ---
                Log.d("HintToggleDebug", "VM: refreshAllHistory calling refreshHintHistory, includeFound = $includeFound")
                // ---
                repository.refreshHintHistory(currentRoomId, includeFound)
            } catch (e: Exception) {
                errorMessage.value = "Hint Refresh failed: ${e.message}"
                Log.e("HistoryViewModel", "Error refreshing hint history", e)
            } finally {
                isLoading.value = false
                Log.d("HistoryViewModel", "Background refresh complete.")
            }
        }
    }

    fun onSearchQueryChanged(query: String) {
        searchQuery.value = query
    }
}