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

    val isLoading = _isLoadingRooms.asStateFlow()

    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    private val _archivedRooms = MutableStateFlow<List<Room>>(emptyList())
    val archivedRooms: StateFlow<List<Room>> = _archivedRooms.asStateFlow()

    private val _isLoadingArchived = MutableStateFlow(false)
    val isLoadingArchived = _isLoadingArchived.asStateFlow()

    init {
        val roomDao = AppDatabase.getInstance(application).roomDao()
        repository = RoomsRepository(RetrofitClient.instance, roomDao)

        viewModelScope.launch {
            repository.allRooms
                .map { roomEntities ->
                    roomEntities.map { RoomMapper.toDomain(it) }
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

    fun reorderRooms(fromIndex: Int, toIndex: Int) {
        val currentList = _rooms.value.toMutableList()

        // Safety checks
        if (fromIndex == toIndex ||
            fromIndex !in currentList.indices ||
            toIndex !in currentList.indices
        ) return

        // 1. Move item in memory immediately for UI responsiveness
        val item = currentList.removeAt(fromIndex)
        currentList.add(toIndex, item)

        // 2. Update StateFlow immediately
        _rooms.value = currentList.toList()

        // 3. Persist new order to DB using Mapper
        viewModelScope.launch {
            // The Mapper.toEntityList helper will assign sort_order based on list index
            val updatedEntities = RoomMapper.toEntityList(currentList)
            repository.updateRoomOrder(updatedEntities)
        }
    }

    fun fetchRooms() {
        _isLoadingRooms.value = true
        viewModelScope.launch {
            try {
                repository.refreshRooms()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to refresh rooms. Check connection."
                e.printStackTrace()
            } finally {
                _isLoadingRooms.value = false
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
                // Explicitly set is_archived to null so we don't accidentally unarchive
                val request = UpdateRoomRequest(alias = newAlias, icon_name = iconName, is_archived = null)
                RetrofitClient.instance.updateRoom(roomId, request)
                repository.refreshRooms()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to update room."
                e.printStackTrace()
            }
        }
    }
    fun fetchArchivedRooms() {
        _isLoadingArchived.value = true
        viewModelScope.launch {
            try {
                // Call API with archived=true
                val result = RetrofitClient.instance.getRooms(archived = true)
                _archivedRooms.value = result
            } catch (e: Exception) {
                _errorMessage.value = "Failed to load archived rooms."
                e.printStackTrace()
            } finally {
                _isLoadingArchived.value = false
            }
        }
    }

    // --- Archive a Room ---
    fun archiveRoom(roomId: Int) {
        viewModelScope.launch {
            try {
                // We send ONLY the is_archived flag.
                // We pass null for alias/icon so they don't change.
                val request = UpdateRoomRequest(is_archived = true)
                RetrofitClient.instance.updateRoom(roomId, request)

                // Refresh both lists to update UI
                repository.refreshRooms() // Updates active list
                fetchArchivedRooms()      // Updates archived list
            } catch (e: Exception) {
                _errorMessage.value = "Failed to archive room."
                e.printStackTrace()
            }
        }
    }

    // --- Unarchive a Room ---
    fun unarchiveRoom(roomId: Int) {
        viewModelScope.launch {
            try {
                val request = UpdateRoomRequest(is_archived = false)
                RetrofitClient.instance.updateRoom(roomId, request)

                repository.refreshRooms()
                fetchArchivedRooms()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to restore room."
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

        viewModelScope.launch {
            try {
                RetrofitClient.instance.syncCheeseTracker()
                _isSyncingCheese.value = false
                fetchRooms()
            } catch (e: Exception) {
                e.printStackTrace()
                Log.w("RoomsViewModel", "Background sync failed: ${e.message}")
                _errorMessage.value = "Background sync failed."
                _isSyncingCheese.value = false
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