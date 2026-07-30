package com.jones.aptracker.ui

import android.app.Application
import android.util.Log
import androidx.lifecycle.*
import com.jones.aptracker.MyFirebaseMessagingService
import com.jones.aptracker.network.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.database.CachedDatapackageEntity

class TextClientViewModel : ViewModel() {

    private val _connectionStatus = MutableStateFlow(ConnectionStatus.DISCONNECTED)
    val connectionStatus = _connectionStatus.asStateFlow()

    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages = _messages.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error = _error.asStateFlow()

    private val _isAutocompleteLoading = MutableStateFlow(false)
    val isAutocompleteLoading = _isAutocompleteLoading.asStateFlow()

    private val _availableItems = MutableStateFlow<List<AutocompleteOption>>(emptyList())
    val availableItems = _availableItems.asStateFlow()

    private val _availableLocations = MutableStateFlow<List<AutocompleteOption>>(emptyList())
    val availableLocations = _availableLocations.asStateFlow()

    private val _datapackage = MutableStateFlow<RoomDatapackage?>(null)
    val datapackage = _datapackage.asStateFlow()

    private val _keepScreenOn = MutableStateFlow(false)
    val keepScreenOn = _keepScreenOn.asStateFlow()

    fun setKeepScreenOn(enabled: Boolean) {
        _keepScreenOn.value = enabled
    }

    private var wsManager: ArchipelagoWebSocketManager? = null
    private var backgroundJob: Job? = null
    private var isAppInBackground = false
    private val TAG = "TextClientVM"

    fun connect(host: String, slotName: String, game: String, password: String?) {
        wsManager?.disconnect()
        
        wsManager = ArchipelagoWebSocketManager(
            host = host,
            slotName = slotName,
            game = game,
            password = password,
            listener = object : ArchipelagoWebSocketManager.ArchipelagoEventListener {
                override fun onStatusChanged(status: ConnectionStatus) {
                    _connectionStatus.value = status
                    if (status == ConnectionStatus.CONNECTED) {
                        _error.value = null
                    }
                }

                override fun onMessageReceived(message: ChatMessage) {
                    // Limit message history to 500 to avoid memory/performance issues
                    _messages.update { it.takeLast(499) + message }
                }

                override fun onError(error: String) {
                    _error.value = error
                }
            }
        )
        wsManager?.connect()
    }

    fun disconnect() {
        wsManager?.disconnect()
        wsManager = null
        _connectionStatus.value = ConnectionStatus.DISCONNECTED
        _messages.value = emptyList()
    }

    fun sendMessage(text: String) {
        wsManager?.sendMessage(text)
    }

    fun onAppBackgrounded() {
        if (connectionStatus.value == ConnectionStatus.CONNECTED || connectionStatus.value == ConnectionStatus.CONNECTING) {
            isAppInBackground = true
            Log.d(TAG, "App backgrounded. Starting 2-minute disconnect timer.")
            backgroundJob?.cancel()
            backgroundJob = viewModelScope.launch {
                delay(120_000) // 2 minutes
                if (isAppInBackground) {
                    Log.d(TAG, "2 minutes elapsed in background. Disconnecting console.")
                    disconnect()
                }
            }
        }
    }

    fun onAppForegrounded() {
        Log.d(TAG, "App foregrounded. Cancelling disconnect timer.")
        isAppInBackground = false
        backgroundJob?.cancel()
    }

    private var lastAutocompleteKey: String? = null

    fun fetchAutocompleteData(roomDbId: Int, slotId: Int, gameName: String? = null, application: Application? = null) {
        val key = if (!gameName.isNullOrEmpty()) "game:$gameName" else "slot:$roomDbId:$slotId"

        if (lastAutocompleteKey == key && _availableItems.value.isNotEmpty()) {
            _isAutocompleteLoading.value = false
            return
        }

        viewModelScope.launch {
            var hasCachedData = false

            if (application != null) {
                try {
                    val db = AppDatabase.getInstance(application)
                    val localCache = db.datapackageDao().getDatapackage(
                        key = key,
                        roomDbId = roomDbId,
                        slotId = slotId,
                        game = gameName
                    )
                    if (localCache != null) {
                        val type = object : TypeToken<List<AutocompleteOption>>() {}.type
                        val cachedItems: List<AutocompleteOption> = Gson().fromJson(localCache.itemsJson, type)
                        val cachedLocs: List<AutocompleteOption> = Gson().fromJson(localCache.locationsJson, type)
                        if (cachedItems.isNotEmpty()) {
                            _availableItems.value = cachedItems
                            hasCachedData = true
                        }
                        if (cachedLocs.isNotEmpty()) _availableLocations.value = cachedLocs
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Failed reading local datapackage cache", e)
                }
            }

            if (hasCachedData) {
                _isAutocompleteLoading.value = false
                lastAutocompleteKey = key
            } else {
                if (_isAutocompleteLoading.value) return@launch
                _isAutocompleteLoading.value = true
            }

            try {
                supervisorScope {
                    val itemsDeferred = async { RetrofitClient.instance.getAvailableItems(roomDbId, slotId) }
                    val locationsDeferred = async { RetrofitClient.instance.getAvailableLocations(roomDbId, slotId) }
                    val datapackageDeferred = async { RetrofitClient.instance.getRoomDatapackage(roomDbId) }

                    val remoteItems = try { itemsDeferred.await() } catch (e: Exception) { 
                        Log.e(TAG, "Items fetch failed", e)
                        emptyList() 
                    }
                    val remoteLocations = try { locationsDeferred.await() } catch (e: Exception) { 
                        Log.e(TAG, "Locations fetch failed", e)
                        emptyList() 
                    }

                    if (remoteItems.isNotEmpty()) _availableItems.value = remoteItems
                    if (remoteLocations.isNotEmpty()) _availableLocations.value = remoteLocations
                    lastAutocompleteKey = key

                    if (application != null && (remoteItems.isNotEmpty() || remoteLocations.isNotEmpty())) {
                        val gson = Gson()
                        val itemsJson = gson.toJson(remoteItems)
                        val locsJson = gson.toJson(remoteLocations)
                        val db = AppDatabase.getInstance(application)

                        db.datapackageDao().insertDatapackage(
                            CachedDatapackageEntity(
                                cacheKey = "slot:$roomDbId:$slotId",
                                game = gameName,
                                roomDbId = roomDbId,
                                slotId = slotId,
                                itemsJson = itemsJson,
                                locationsJson = locsJson,
                                updatedAt = System.currentTimeMillis()
                            )
                        )

                        if (!gameName.isNullOrEmpty()) {
                            db.datapackageDao().insertDatapackage(
                                CachedDatapackageEntity(
                                    cacheKey = "game:$gameName",
                                    game = gameName,
                                    roomDbId = roomDbId,
                                    slotId = slotId,
                                    itemsJson = itemsJson,
                                    locationsJson = locsJson,
                                    updatedAt = System.currentTimeMillis()
                                )
                            )
                        }
                    }

                    _datapackage.value = try { 
                        val result = datapackageDeferred.await()
                        Log.d(TAG, "Datapackage fetched: ${result.players.size} players")
                        result
                    } catch (e: Exception) { 
                        Log.e(TAG, "Datapackage fetch failed", e)
                        null 
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to fetch autocomplete/datapackage", e)
            } finally {
                _isAutocompleteLoading.value = false
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        disconnect()
    }
}
