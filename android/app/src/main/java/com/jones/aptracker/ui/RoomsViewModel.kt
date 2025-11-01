package com.jones.aptracker.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.network.AddRoomRequest
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.Room
import com.jones.aptracker.network.UpdateRoomRequest
import com.jones.aptracker.repository.RoomsRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

class RoomsViewModel(application: Application) : AndroidViewModel(application) {

    // --- SETUP THE REPOSITORY ---
    private val repository: RoomsRepository

    private val _rooms = MutableStateFlow<List<Room>>(emptyList())
    val rooms: StateFlow<List<Room>> = _rooms

    val isLoading = MutableStateFlow(true)

    // --- NEW: Add the error message StateFlow ---
    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    init {
        // --- INITIALIZE the database and repository ---
        val roomDao = AppDatabase.getInstance(application).roomDao()
        repository = RoomsRepository(RetrofitClient.instance, roomDao)

        // --- OBSERVE the database for changes ---
        viewModelScope.launch {
            repository.allRooms
                .map { roomEntities ->
                    roomEntities.map { entity ->
                        Room(
                            id = entity.id,
                            room_id = entity.room_id,
                            alias = entity.alias,
                            host = entity.host,
                            tracked_slots_count = entity.tracked_slots_count,
                            total_slots_count = entity.total_slots_count,
                            icon_name = entity.icon_name
                        )
                    }
                }
                .catch {
                    _errorMessage.value = "Failed to load rooms from database."
                    it.printStackTrace()
                }
                .collect { roomList ->
                    _rooms.value = roomList
                    if (roomList.isNotEmpty()) {
                        isLoading.value = false
                    }
                }
        }
        // --- TRIGGER the initial refresh ---
        fetchRooms()
    }

    fun fetchRooms() {
        isLoading.value = true
        viewModelScope.launch {
            try {
                repository.refreshRooms()
            } catch (e: Exception) {
                // --- FIXED: Set error message ---
                _errorMessage.value = "Failed to refresh rooms. Check connection."
                e.printStackTrace()
            } finally {
                isLoading.value = false
            }
        }
    }

    fun addRoom(roomUrl: String, alias: String, iconName: String) {
        viewModelScope.launch {
            _errorMessage.value = null // Clear any old errors
            try {
                val request = AddRoomRequest(room_url = roomUrl, alias = alias, icon_name = iconName)

                // --- START FIX ---
                // Capture the response from the Retrofit call
                val response = RetrofitClient.instance.addRoom(request)

                if (response.isSuccessful) {
                    // Only refresh if the add was successful
                    repository.refreshRooms()
                } else {
                    // Manually set the error message from the 400 response
                    _errorMessage.value = "Failed to add room. Check URL or connection."
                    // Optional: You could parse the JSON error from your server
                    // val errorMsg = response.errorBody()?.string()
                    // _errorMessage.value = "Error: $errorMsg"
                }
                // --- END FIX ---

            } catch (e: Exception) {
                // This catch block will now only handle actual network/connection errors
                _errorMessage.value = "Failed to add room. Check connection."
                e.printStackTrace()
            }
        }
    }

    fun deleteRoom(roomId: Int) {
        viewModelScope.launch {
            try {
                RetrofitClient.instance.deleteRoom(roomId)
                repository.refreshRooms()
            } catch (e: Exception) {
                // --- FIXED: Set error message ---
                _errorMessage.value = "Failed to delete room."
                e.printStackTrace()
            }
        }
    }

    fun updateRoom(roomId: Int, newAlias: String, iconName: String) {
        viewModelScope.launch {
            try {
                val request = UpdateRoomRequest(alias = newAlias, icon_name = iconName)
                RetrofitClient.instance.updateRoom(roomId, request)
                repository.refreshRooms()
            } catch (e: Exception) {
                // --- FIXED: Set error message ---
                _errorMessage.value = "Failed to update room."
                e.printStackTrace()
            }
        }
    }

    // --- NEW: Add the clear function ---
    fun clearErrorMessage() {
        _errorMessage.value = null
    }
}