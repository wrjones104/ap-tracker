package com.jones.aptracker.ui

import android.app.Application
import android.util.Log
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.network.HintEntity
import com.jones.aptracker.network.HistoryItem
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.repository.UserRepository
import com.jones.aptracker.repository.HistoryRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import retrofit2.HttpException

class HistoryViewModel(application: Application) : AndroidViewModel(application) {

    private val repository: HistoryRepository
    private val userRepository: UserRepository
    private val _itemHistory = MutableStateFlow<List<HistoryItem>>(emptyList())
    val itemHistory: StateFlow<List<HistoryItem>> = _itemHistory

    private val _hintsForYou = MutableStateFlow<List<HintEntity>>(emptyList())
    val hintsForYou: StateFlow<List<HintEntity>> = _hintsForYou

    private val _hintsByYou = MutableStateFlow<List<HintEntity>>(emptyList())
    val hintsByYou: StateFlow<List<HintEntity>> = _hintsByYou

    val searchQuery = mutableStateOf("")
    val isLoading = MutableStateFlow(true)
    val errorMessage = mutableStateOf<String?>(null)

    private val _showFoundHints = MutableStateFlow(false)
    val showFoundHints: StateFlow<Boolean> = _showFoundHints

    private val _showFinished = MutableStateFlow(true)
    val showFinished: StateFlow<Boolean> = _showFinished

    val finishedPlayerKeys: StateFlow<Set<Pair<Int, String>>> = _itemHistory.map { history ->
        history.filter { it.isPlayerFinished && it.db_id != null }
            .map { it.db_id!! to it.playerName }
            .toSet()
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptySet())

    private var currentRoomId: Int? = null

    private val _selectedPlayerFilter = MutableStateFlow<String?>(null)
    val selectedPlayerFilter: StateFlow<String?> = _selectedPlayerFilter

    val availablePlayers: StateFlow<List<String>> = _itemHistory.map { history ->
        history.map { it.playerName }.distinct().sorted()
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    private val _actionMessage = MutableStateFlow<String?>(null)
    val actionMessage: StateFlow<String?> = _actionMessage

    init {
        val db = AppDatabase.getInstance(application)
        val historyDao = db.historyDao()
        val hintDao = db.hintDao()

        val apiService = RetrofitClient.instance
        repository = HistoryRepository(apiService, historyDao, hintDao)
        userRepository = UserRepository(apiService)
    }

    fun loadHistoryFor(roomId: Int?) {
        currentRoomId = roomId
        Log.d("HistoryViewModel", "Loading history for Room ID: ${roomId ?: "Global"}")

        refreshAllHistory()
    }

    fun setShowFoundHints(show: Boolean) {
        if (show == _showFoundHints.value) {
            Log.d("HintToggleDebug", "VM: setShowFoundHints called with same value: $show. Skipping.")
            return
        }
        Log.d("HintToggleDebug", "VM: setShowFoundHints NEW value: $show")
        _showFoundHints.value = show

        refreshAllHistory()
    }

    fun setShowFinished(show: Boolean) {
        _showFinished.value = show
    }

    fun refreshAllHistory() {
        Log.d("HistoryViewModel", "Triggering refresh for Room ID: ${currentRoomId ?: "Global"}")
        viewModelScope.launch {
            isLoading.value = true
            errorMessage.value = null

            try {
                repository.refreshItemHistory()

                val itemEntities = if (currentRoomId != null) {
                    repository.getHistoryForRoom(currentRoomId!!)
                } else {
                    repository.getGlobalHistory()
                }

                _itemHistory.value = itemEntities.map { entity ->
                    HistoryItem(
                        id = entity.id,
                        playerName = entity.playerName,
                        itemName = entity.itemName,
                        isPlayerFinished = entity.isPlayerFinished,
                        itemFlags = entity.itemFlags,
                        timestamp = entity.timestamp,
                        tracker_id = entity.tracker_id,
                        slot_id = entity.slot_id,
                        icon_name = entity.icon_name,
                        db_id = entity.roomId,
                        host = entity.host,
                        receivingGame = entity.receivingGame,
                        senderName = entity.senderName,
                        senderGame = entity.senderGame,
                        locationName = entity.locationName
                    )
                }

                val includeFound = _showFoundHints.value
                Log.d("HintToggleDebug", "VM: refreshAllHistory calling refreshHintHistory, includeFound = $includeFound")
                repository.refreshHintHistory(currentRoomId, includeFound)

                val (forYou, byYou) = if (currentRoomId != null) {
                    repository.getHintsForRoom(currentRoomId!!, includeFound)
                } else {
                    repository.getGlobalHints(includeFound)
                }
                _hintsForYou.value = forYou
                _hintsByYou.value = byYou
                Log.d("HistoryViewModel", "Loaded ${forYou.size} hints for you, ${byYou.size} hints by you.")

            } catch (e: Exception) {
                errorMessage.value = "History Refresh failed: ${e.message}"
                Log.e("HistoryViewModel", "Error during full history refresh", e)
            } finally {
                isLoading.value = false
                Log.d("HistoryViewModel", "Full refresh complete.")
            }
        }
    }

    fun onSearchQueryChanged(query: String) {
        searchQuery.value = query
    }
    fun clearErrorMessage() {
        errorMessage.value = null
    }

    fun onPlayerFilterSelected(player: String?) {
        if (_selectedPlayerFilter.value == player) {
            _selectedPlayerFilter.value = null
        } else {
            _selectedPlayerFilter.value = player
        }
    }

    fun ignoreItem(itemName: String, gameName: String?) {
        viewModelScope.launch {
            try {
                userRepository.addIgnoreItem(itemName, gameName)
                _actionMessage.value = "Ignored '$itemName'"
            } catch (e: HttpException) {
                if (e.code() == 409) {
                    errorMessage.value = "'$itemName' is already on your ignore list."
                } else {
                    Log.e("HistoryViewModel", "Failed to ignore item (HTTP ${e.code()})", e)
                    errorMessage.value = "Failed to ignore item."
                }
            } catch (e: Exception) {
                Log.e("HistoryViewModel", "Failed to ignore item", e)
                errorMessage.value = "Failed to ignore item. Check connection."
            }
        }
    }
    fun clearActionMessage() {
        _actionMessage.value = null
    }
}