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

    private val repository: RoomsRepository

    private val _rooms = MutableStateFlow<List<Room>>(emptyList())
    val rooms: StateFlow<List<Room>> = _rooms

    val isLoading = MutableStateFlow(true)

    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    init {
        val roomDao = AppDatabase.getInstance(application).roomDao()
        repository = RoomsRepository(RetrofitClient.instance, roomDao)

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
        fetchRooms()
    }

    fun fetchRooms() {
        isLoading.value = true
        viewModelScope.launch {
            try {
                repository.refreshRooms()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to refresh rooms. Check connection."
                e.printStackTrace()
            } finally {
                isLoading.value = false
            }
        }
    }

// In RoomsViewModel.kt

    fun addRoom(
        roomUrl: String,
        alias: String,
        iconName: String,
        onSuccess: () -> Unit
    ) {
        viewModelScope.launch {
            _errorMessage.value = null
            try {
                val request = AddRoomRequest(room_url = roomUrl, alias = alias, icon_name = iconName)
                val response = RetrofitClient.instance.addRoom(request)

                if (response.isSuccessful) {
                    repository.refreshRooms()
                    onSuccess()
                } else {
                    _errorMessage.value = "Failed to add room. Check URL or connection."
                }

            } catch (e: Exception) {
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
                _errorMessage.value = "Failed to update room."
                e.printStackTrace()
            }
        }
    }

    fun clearErrorMessage() {
        _errorMessage.value = null
    }
}