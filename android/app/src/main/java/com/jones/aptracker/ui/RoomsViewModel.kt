package com.jones.aptracker.ui

import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.network.AddRoomRequest
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.Room
import com.jones.aptracker.network.UpdateRoomRequest
import kotlinx.coroutines.launch

class RoomsViewModel : ViewModel() {
    val rooms = mutableStateOf<List<Room>>(emptyList())
    val isLoading = mutableStateOf(true)

    init {
        fetchRooms()
    }

    // --- RENAME THIS FUNCTION to make it public ---
    fun fetchRooms() {
        isLoading.value = true // Show loading spinner on refresh
        viewModelScope.launch {
            try {
                val roomList = RetrofitClient.instance.getRooms()
                rooms.value = roomList
            } catch (e: Exception) {
                e.printStackTrace()
            } finally {
                isLoading.value = false
            }
        }
    }

    // --- ADD THIS FUNCTION ---
    fun addRoom(roomId: String, alias: String) {
        viewModelScope.launch {
            try {
                val request = AddRoomRequest(room_id = roomId, alias = alias)
                RetrofitClient.instance.addRoom(request)
                // After adding, refresh the list to show the new room
                fetchRooms()
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }
    }

    fun deleteRoom(roomId: Int) {
        viewModelScope.launch {
            try {
                RetrofitClient.instance.deleteRoom(roomId)
                // After deleting, refresh the list to remove it from the UI
                fetchRooms()
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }
    }

    fun updateRoom(roomId: Int, newAlias: String) {
        viewModelScope.launch {
            try {
                val request = UpdateRoomRequest(alias = newAlias)
                RetrofitClient.instance.updateRoom(roomId, request)
                fetchRooms() // Refresh the list to show the new name
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }
    }
}