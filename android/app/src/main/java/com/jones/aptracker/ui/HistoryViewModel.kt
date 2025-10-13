package com.jones.aptracker.ui

import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.network.HistoryItem // **THE FIX**: Import the new class
import com.jones.aptracker.network.RetrofitClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class HistoryViewModel : ViewModel() {
    val itemHistory = mutableStateOf<List<HistoryItem>>(emptyList()) // **THE FIX**
    val hintHistory = mutableStateOf<List<HistoryItem>>(emptyList()) // **THE FIX**
    val isLoading = mutableStateOf(true)
    val errorMessage = mutableStateOf<String?>(null)

    fun fetchHistory(roomId: Int) {
        isLoading.value = true
        errorMessage.value = null
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val items = RetrofitClient.instance.getItemHistory(roomId)
                val hints = RetrofitClient.instance.getHintHistory(roomId)

                withContext(Dispatchers.Main) {
                    itemHistory.value = items
                    hintHistory.value = hints
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