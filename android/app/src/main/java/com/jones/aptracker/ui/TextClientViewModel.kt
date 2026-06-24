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
import kotlinx.coroutines.launch

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

    fun fetchAutocompleteData(roomDbId: Int, slotId: Int) {
        _isAutocompleteLoading.value = true
        viewModelScope.launch {
            try {
                supervisorScope {
                    val itemsDeferred = async { RetrofitClient.instance.getAvailableItems(roomDbId, slotId) }
                    val locationsDeferred = async { RetrofitClient.instance.getAvailableLocations(roomDbId, slotId) }
                    val datapackageDeferred = async { RetrofitClient.instance.getRoomDatapackage(roomDbId) }

                    _availableItems.value = try { itemsDeferred.await() } catch (e: Exception) { 
                        Log.e(TAG, "Items fetch failed", e)
                        emptyList() 
                    }
                    _availableLocations.value = try { locationsDeferred.await() } catch (e: Exception) { 
                        Log.e(TAG, "Locations fetch failed", e)
                        emptyList() 
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
