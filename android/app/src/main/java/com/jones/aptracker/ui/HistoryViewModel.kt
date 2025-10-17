package com.jones.aptracker.ui

import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.network.HistoryItem
import com.jones.aptracker.network.RetrofitClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class HistoryViewModel : ViewModel() {
    val itemHistory = mutableStateOf<List<HistoryItem>>(emptyList())
    // hintHistory is removed as the endpoint is gone
    val isLoading = mutableStateOf(true)
    val errorMessage = mutableStateOf<String?>(null)

    fun fetchHistory(roomId: Int) {
        isLoading.value = true
        errorMessage.value = null
        viewModelScope.launch(Dispatchers.IO) {
            try {
                // Only fetch item history now
                val items = RetrofitClient.instance.getItemHistory(roomId)

                withContext(Dispatchers.Main) {
                    itemHistory.value = items
                    isLoading.value = false
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    errorMessage.value = "Failed to load history: ${e.message}"
                    isLoading.value = false
                }
                e.printStackTrace()
            }
        }
    }
}
