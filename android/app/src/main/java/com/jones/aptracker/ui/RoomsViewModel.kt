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
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

class RoomsViewModel(application: Application) : AndroidViewModel(application) {

    // --- SETUP THE REPOSITORY ---
    private val repository: RoomsRepository

    private val _rooms = MutableStateFlow<List<Room>>(emptyList())
    val rooms: StateFlow<List<Room>> = _rooms

    val isLoading = MutableStateFlow(true)

    init {
        // --- INITIALIZE the database and repository ---
        val roomDao = AppDatabase.getInstance(application).roomDao()
        repository = RoomsRepository(RetrofitClient.instance, roomDao)

        // --- OBSERVE the database for changes ---
        viewModelScope.launch {
            // Listen to the flow of rooms from the repository
            repository.allRooms
                .map { roomEntities ->
                    // Convert database entities back to UI models
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
                    // Handle any errors from the database flow
                    it.printStackTrace()
                }
                .collect { roomList ->
                    _rooms.value = roomList
                    // If we have data, we are not in the initial "loading" state
                    // The refresh indicator is handled separately.
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
                // The UI will continue showing the cached data.
                // You could optionally show a Snackbar here to inform the user.
                e.printStackTrace()
            } finally {
                isLoading.value = false
            }
        }
    }

    fun addRoom(roomId: String, alias: String, iconName: String) {
        viewModelScope.launch {
            try {
                val request = AddRoomRequest(room_id = roomId, alias = alias, icon_name = iconName)
                RetrofitClient.instance.addRoom(request)
                repository.refreshRooms()
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
                repository.refreshRooms()
            } catch (e: Exception) {
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
                e.printStackTrace()
            }
        }
    }
}