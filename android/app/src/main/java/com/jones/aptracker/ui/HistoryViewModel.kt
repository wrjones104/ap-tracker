package com.jones.aptracker.ui

import android.app.Application
import android.util.Log
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.network.HintEntity
import com.jones.aptracker.network.HistoryItem
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.repository.HistoryRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

class HistoryViewModel(application: Application) : AndroidViewModel(application) {

    private val repository: HistoryRepository
    private val _itemHistory = MutableStateFlow<List<HistoryItem>>(emptyList())
    val itemHistory: StateFlow<List<HistoryItem>> = _itemHistory

    private val _hintsForYou = MutableStateFlow<List<HintEntity>>(emptyList())
    val hintsForYou: StateFlow<List<HintEntity>> = _hintsForYou

    private val _hintsByYou = MutableStateFlow<List<HintEntity>>(emptyList())
    val hintsByYou: StateFlow<List<HintEntity>> = _hintsByYou

    val searchQuery = mutableStateOf("")
    val isLoading = MutableStateFlow(true)
    val errorMessage = mutableStateOf<String?>(null)

    private val _showFoundHints = MutableStateFlow(false)
    val showFoundHints: StateFlow<Boolean> = _showFoundHints

    private var currentRoomId: Int? = null

    init {
        val db = AppDatabase.getInstance(application)
        val historyDao = db.historyDao()
        val hintDao = db.hintDao()
        repository = HistoryRepository(RetrofitClient.instance, historyDao, hintDao)
    }

    fun loadHistoryFor(roomId: Int?) {
        currentRoomId = roomId
        Log.d("HistoryViewModel", "Loading history for Room ID: ${roomId ?: "Global"}")

        refreshAllHistory()
    }


    fun setShowFoundHints(show: Boolean) {
        if (show == _showFoundHints.value) {
            Log.d("HintToggleDebug", "VM: setShowFoundHints called with same value: $show. Skipping.")
            return
        }
        Log.d("HintToggleDebug", "VM: setShowFoundHints NEW value: $show")
        _showFoundHints.value = show

        // --- SIMPLIFIED: Just call refreshAllHistory with the new toggle value ---
        refreshAllHistory()
    }

    fun refreshAllHistory() {
        Log.d("HistoryViewModel", "Triggering refresh for Room ID: ${currentRoomId ?: "Global"}")
        viewModelScope.launch {
            isLoading.value = true
            errorMessage.value = null

            try {
                // 1. Refresh Item History (Network)
                repository.refreshItemHistory()

                // 2. Fetch fresh items from DB
                // --- THIS IS THE FIX ---
                val itemEntities = if (currentRoomId != null) {
                    repository.getHistoryForRoom(currentRoomId!!)
                } else {
                    repository.getGlobalHistory()
                }

                _itemHistory.value = itemEntities.map { entity ->
                    HistoryItem(
                        message = entity.message,
                        timestamp = entity.timestamp,
                        tracker_id = entity.tracker_id,
                        slot_id = entity.slot_id,
                        icon_name = entity.icon_name,
                        db_id = entity.roomId
                    )
                }
                // --- END FIX ---

                // 3. Refresh Hint History (Network)
                val includeFound = _showFoundHints.value
                Log.d("HintToggleDebug", "VM: refreshAllHistory calling refreshHintHistory, includeFound = $includeFound")
                repository.refreshHintHistory(currentRoomId, includeFound)

                // 4. Fetch fresh hints from DB
                val (forYou, byYou) = if (currentRoomId != null) {
                    repository.getHintsForRoom(currentRoomId!!, includeFound)
                } else {
                    repository.getGlobalHints(includeFound)
                }
                _hintsForYou.value = forYou
                _hintsByYou.value = byYou
                Log.d("HistoryViewModel", "Loaded ${forYou.size} hints for you, ${byYou.size} hints by you.")

            } catch (e: Exception) {
                errorMessage.value = "History Refresh failed: ${e.message}"
                Log.e("HistoryViewModel", "Error during full history refresh", e)
            } finally {
                isLoading.value = false
                Log.d("HistoryViewModel", "Full refresh complete.")
            }
        }
    }

    fun onSearchQueryChanged(query: String) {
        searchQuery.value = query
    }
    fun clearErrorMessage() {
        errorMessage.value = null
    }
}