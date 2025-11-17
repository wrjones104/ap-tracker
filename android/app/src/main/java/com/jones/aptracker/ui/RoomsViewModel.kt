package com.jones.aptracker.ui

import android.app.Application
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.data.SettingsManager
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.network.AddRoomRequest
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.Room
import com.jones.aptracker.network.UpdateRoomRequest
import com.jones.aptracker.repository.RoomsRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

// Removed unused delay import

class RoomsViewModel(application: Application) : AndroidViewModel(application) {

    private val repository: RoomsRepository
    private val settingsManager = SettingsManager(application)

    private val _isSyncingCheese = MutableStateFlow(false)
    val isSyncingCheese: StateFlow<Boolean> = _isSyncingCheese.asStateFlow()

    val isAutoSyncEnabled = settingsManager.isAutoSyncEnabled.stateIn(
        viewModelScope,
        SharingStarted.Eagerly,
        true
    )

    private val _rooms = MutableStateFlow<List<Room>>(emptyList())
    val rooms: StateFlow<List<Room>> = _rooms

    private val _isLoadingRooms = MutableStateFlow(true)

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
                }
        }

        fetchRooms()
    }

    private fun updateCombinedLoadingState() {
        isLoading.value = _isLoadingRooms.value || _isSyncingCheese.value
    }

    fun fetchRooms() {
        _isLoadingRooms.value = true
        updateCombinedLoadingState()
        viewModelScope.launch {
            try {
                repository.refreshRooms()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to refresh rooms. Check connection."
                e.printStackTrace()
            } finally {
                _isLoadingRooms.value = false
                updateCombinedLoadingState()
            }
        }
    }

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

    private fun triggerBackgroundSync() {
        if (_isSyncingCheese.value) return
        _isSyncingCheese.value = true
        updateCombinedLoadingState()
        viewModelScope.launch {
            try {
                RetrofitClient.instance.syncCheeseTracker()
                _isSyncingCheese.value = false
                updateCombinedLoadingState()
                fetchRooms()
            } catch (e: Exception) {
                e.printStackTrace()
                Log.w("RoomsViewModel", "Background sync failed: ${e.message}")
                _errorMessage.value = "Background sync failed."
                _isSyncingCheese.value = false
                updateCombinedLoadingState()
            }
        }
    }

    fun refreshAll(isCheeseConnected: Boolean, forceCheeseSync: Boolean = false) {
        val shouldSyncCheese = isCheeseConnected && (forceCheeseSync || isAutoSyncEnabled.value)

        if (shouldSyncCheese && _isSyncingCheese.value) return

        if (shouldSyncCheese) {
            triggerBackgroundSync()
        } else {
            fetchRooms()
        }
    }
}