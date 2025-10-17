package com.jones.aptracker.ui

import android.app.Application
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.database.AppDatabase
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
    val searchQuery = mutableStateOf("")
    val isLoading = MutableStateFlow(true)
    val errorMessage = mutableStateOf<String?>(null)

    init {
        val historyDao = AppDatabase.getInstance(application).historyDao()
        repository = HistoryRepository(RetrofitClient.instance, historyDao)
    }

    fun loadHistoryFor(roomId: Int?) {
        viewModelScope.launch {
            isLoading.value = true
            errorMessage.value = null

            val historyFlow = if (roomId != null) {
                repository.getHistoryForRoom(roomId)
            } else {
                repository.getGlobalHistory()
            }

            historyFlow
                .map { entities ->
                    entities.map { entity ->
                        HistoryItem(
                            message = entity.message,
                            timestamp = entity.timestamp,
                            tracker_id = entity.tracker_id,
                            slot_id = entity.slot_id,
                            icon_name = entity.icon_name,
                            db_id = entity.roomId // Pass it along for the UI if needed
                        )
                    }
                }
                .catch { e ->
                    errorMessage.value = "Failed to load from database: ${e.message}"
                    e.printStackTrace()
                }
                .collect { historyList ->
                    _itemHistory.value = historyList
                    isLoading.value = false
                }
        }

        // Always trigger a single, unified refresh in the background.
        refreshHistory()
    }

    private fun refreshHistory() {
        viewModelScope.launch {
            try {
                repository.refreshHistory()
            } catch (e: Exception) {
                errorMessage.value = "Refresh failed: ${e.message}"
                e.printStackTrace()
            }
        }
    }

    fun onSearchQueryChanged(query: String) {
        searchQuery.value = query
    }
}