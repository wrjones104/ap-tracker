package com.jones.aptracker.ui

import android.app.Application
import android.util.Log
import android.widget.Toast
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.data.SettingsManager
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.network.AddRoomRequest
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.Room
import com.jones.aptracker.network.UpdateRoomRequest
import com.jones.aptracker.repository.RoomsRepository
import com.jones.aptracker.repository.UserRepository // Import this!
import kotlinx.coroutines.delay
import kotlinx.coroutines.Job
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
    private val userRepository: UserRepository // Add this
    private val settingsManager = SettingsManager(application)

    private var syncJob: Job? = null
    private var lastFetchTime = 0L
    private val FETCH_COOLDOWN_MS = 10000L // 10 seconds

    private val _isSyncingCheese = MutableStateFlow(false)
    val isSyncingCheese: StateFlow<Boolean> = _isSyncingCheese.asStateFlow()

    private val _isAddingRoom = MutableStateFlow(false)
    val isAddingRoom: StateFlow<Boolean> = _isAddingRoom.asStateFlow()

    val isAutoSyncEnabled = settingsManager.isAutoSyncEnabled.stateIn(
        viewModelScope,
        SharingStarted.Eagerly,
        true
    )

    val isCheeseConnected = settingsManager.isCheeseConnected.stateIn(
        viewModelScope,
        SharingStarted.Eagerly,
        false
    )

    private val _rooms = MutableStateFlow<List<Room>>(emptyList())
    val rooms: StateFlow<List<Room>> = _rooms

    private val _isLoadingRooms = MutableStateFlow(false)
    val isLoading = _isLoadingRooms.asStateFlow()

    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    private val _archivedRooms = MutableStateFlow<List<Room>>(emptyList())
    val archivedRooms: StateFlow<List<Room>> = _archivedRooms.asStateFlow()

    private val _isLoadingArchived = MutableStateFlow(false)
    val isLoadingArchived = _isLoadingArchived.asStateFlow()

    init {
        val roomDao = AppDatabase.getInstance(application).roomDao()
        val api = RetrofitClient.instance
        repository = RoomsRepository(api, roomDao, application)
        userRepository = UserRepository(api)

        viewModelScope.launch {
            repository.allRooms
                .map { roomEntities -> roomEntities.map { RoomMapper.toDomain(it) } }
                .catch { e ->
                    _errorMessage.value = "Failed to load rooms from database."
                    Log.e("RoomsViewModel", "Error loading rooms from DB", e)
                }
                .collect { roomList -> _rooms.value = roomList }
        }

        fetchRooms() // Regular fetch

        viewModelScope.launch {
            delay(1000)
            val isAutoSync = isAutoSyncEnabled.value
            val isCheeseConn = isCheeseConnected.value
            if (isAutoSync && isCheeseConn) {
                triggerBackgroundSync()
            }
        }
    }

    fun reorderRooms(fromIndex: Int, toIndex: Int) {
        val currentList = _rooms.value.toMutableList()
        if (fromIndex == toIndex || fromIndex !in currentList.indices || toIndex !in currentList.indices) return

        val item = currentList.removeAt(fromIndex)
        currentList.add(toIndex, item)
        _rooms.value = currentList.toList()

        viewModelScope.launch {
            val updatedEntities = RoomMapper.toEntityList(currentList)
            repository.updateRoomOrder(updatedEntities)
        }
    }

    fun fetchRooms(force: Boolean = false) {
        if (_isLoadingRooms.value) return
        val now = System.currentTimeMillis()
        if (!force && now - lastFetchTime < FETCH_COOLDOWN_MS) {
            Log.d("RoomsViewModel", "fetchRooms: Cooldown active, skipping fetch.")
            return
        }
        _isLoadingRooms.value = true
        viewModelScope.launch {
            try {
                repository.refreshRooms()
                lastFetchTime = System.currentTimeMillis()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to refresh rooms. Check connection."
                e.printStackTrace()
            } finally {
                _isLoadingRooms.value = false
            }
        }
    }

    fun addRoom(roomUrl: String, alias: String, iconName: String, onSuccess: () -> Unit) {
        viewModelScope.launch {
            _isAddingRoom.value = true
            _errorMessage.value = null
            var cleanUrl = roomUrl.trim()
            if (cleanUrl.isNotEmpty() && !cleanUrl.startsWith("http://") && !cleanUrl.startsWith("https://")) {
                cleanUrl = "https://$cleanUrl"
            }

            try {
                val request = AddRoomRequest(room_url = cleanUrl, alias = alias, icon_name = iconName)

                // FIXED: Use Repository method we just added
                repository.addRoom(request)
                onSuccess()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to add room. Check connection."
                e.printStackTrace()
            } finally {
                _isAddingRoom.value = false
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

    fun reviveRoom(roomId: Int) {
        viewModelScope.launch {
            try {
                repository.reviveRoom(roomId)
            } catch (e: Exception) {
                _errorMessage.value = "Failed to revive room."
                e.printStackTrace()
            }
        }
    }

    fun updateRoom(roomId: Int, newAlias: String, iconName: String) {
        viewModelScope.launch {
            try {
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
                // FIXED: Use Repository method we just added
                val result = repository.refreshArchivedRooms()
                _archivedRooms.value = result
            } catch (e: Exception) {
                _errorMessage.value = "Failed to load archived rooms."
                e.printStackTrace()
            } finally {
                _isLoadingArchived.value = false
            }
        }
    }

    fun archiveRoom(roomId: Int) {
        viewModelScope.launch {
            try {
                val request = UpdateRoomRequest(is_archived = true)
                RetrofitClient.instance.updateRoom(roomId, request)
                repository.refreshRooms()
                fetchArchivedRooms()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to archive room."
                e.printStackTrace()
            }
        }
    }

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

    fun cancelBackgroundSync() {
        syncJob?.cancel()
        _isSyncingCheese.value = false
    }

    private fun triggerBackgroundSync() {
        if (_isSyncingCheese.value) return
        _isSyncingCheese.value = true

        syncJob = viewModelScope.launch {
            try {
                // 1. Tell backend to START syncing
                val response = RetrofitClient.instance.syncCheeseTracker()
                
                // Update local state if the server response contains the status
                response.is_connected?.let {
                    settingsManager.setCheeseConnected(it)
                }

                // 2. Poll until backend says "Done"
                var retries = 0
                while (retries < 15) { // Check for 30 seconds
                    delay(2000)
                    val currentProfile = userRepository.getUserProfile()
                    if (!currentProfile.is_syncing_cheese) {
                        break // Sync complete
                    }
                    retries++
                }

                fetchRooms(force = true)
                Toast.makeText(getApplication(), "Cheese Sync Complete!", Toast.LENGTH_SHORT).show()

            } catch (e: kotlinx.coroutines.CancellationException) {
                Log.i("RoomsViewModel", "Background sync cancelled by user.")
                throw e
            } catch (e: Exception) {
                e.printStackTrace()
                Log.w("RoomsViewModel", "Background sync failed: ${e.message}")
                _errorMessage.value = "Background sync failed."
            } finally {
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
            fetchRooms(force = true)
        }
    }
}