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
import kotlinx.coroutines.flow.combine
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

    val availablePlayers: StateFlow<List<PlayerDisplayInfo>> = _itemHistory.map { history ->
        history.map {
            PlayerDisplayInfo(it.playerName, it.playerAlias)
        }
            .distinct()
            .sorted()
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val availableHintPlayers: StateFlow<List<PlayerDisplayInfo>> = combine(_hintsForYou, _hintsByYou) { forYou, byYou ->
        val players = mutableSetOf<PlayerDisplayInfo>()

        players.addAll(forYou.map { PlayerDisplayInfo(it.itemOwnerName, it.itemOwnerAlias) })
        players.addAll(byYou.map { PlayerDisplayInfo(it.locationOwnerName, it.locationOwnerAlias) })

        players.toList().sorted()
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    private val _actionMessage = MutableStateFlow<String?>(null)
    val actionMessage: StateFlow<String?> = _actionMessage
    private var validTrackedSlots: Set<Pair<Int, Int>> = emptySet()
    private val _useCondensed = MutableStateFlow(false)
    val useCondensed: StateFlow<Boolean> = _useCondensed

    init {
        val db = AppDatabase.getInstance(application)
        val historyDao = db.historyDao()
        val hintDao = db.hintDao()

        val apiService = RetrofitClient.instance
        repository = HistoryRepository(apiService, historyDao, hintDao)
        userRepository = UserRepository(apiService)
        fetchUserPreferences()
    }

    fun loadHistoryFor(roomId: Int?) {
        currentRoomId = roomId
        Log.d("HistoryViewModel", "Loading history for Room ID: ${roomId ?: "Global"}")

        refreshAllHistory()
    }

    private fun fetchUserPreferences() {
        viewModelScope.launch {
            try {
                val profile = RetrofitClient.instance.getUserProfile()
                _useCondensed.value = profile.use_condensed_messages_default
                _showFinished.value = profile.ui_show_finished_default
                _showFoundHints.value = profile.ui_show_found_hints_default
            } catch (e: Exception) {
                Log.e("HistoryViewModel", "Failed to load user profile for settings", e)
            }
        }
    }

    fun setShowFinished(show: Boolean) {
        if (_showFinished.value != show) {
            _showFinished.value = show
            saveViewPreferences(showFinished = show)
        }
    }

    fun setShowFoundHints(show: Boolean) {
        if (_showFoundHints.value != show) {
            _showFoundHints.value = show
            saveViewPreferences(showFoundHints = show)
            refreshAllHistory()
        }
    }

    fun refreshAllHistory() {
        Log.d("HistoryViewModel", "Triggering refresh for Room ID: ${currentRoomId ?: "Global"}")
        viewModelScope.launch {
            isLoading.value = true
            errorMessage.value = null

            try {
                val trackedRooms = RetrofitClient.instance.getUserTrackedSlots()

                validTrackedSlots = trackedRooms.flatMap { room ->
                    room.tracked_slots.map { slot ->
                        room.room_db_id to slot.slot_id
                    }
                }.toSet()

                repository.refreshItemHistory()

                val rawItemEntities = if (currentRoomId != null) {
                    repository.getHistoryForRoom(currentRoomId!!)
                } else {
                    repository.getGlobalHistory()
                }
                _itemHistory.value = rawItemEntities.mapNotNull { entity ->
                    if (entity.roomId != null && entity.slot_id != null) {
                        if (!validTrackedSlots.contains(entity.roomId to entity.slot_id)) {
                            return@mapNotNull null
                        }
                    }

                    HistoryItem(
                        id = entity.id,
                        playerName = entity.playerName,
                        playerAlias = entity.playerAlias,
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
                        senderAlias = entity.senderAlias,
                        senderGame = entity.senderGame,
                        locationName = entity.locationName
                    )
                }

                val includeFound = _showFoundHints.value
                repository.refreshHintHistory(currentRoomId, includeFound)

                val (rawForYou, rawByYou) = if (currentRoomId != null) {
                    repository.getHintsForRoom(currentRoomId!!, includeFound)
                } else {
                    repository.getGlobalHints(includeFound)
                }
                _hintsForYou.value = rawForYou.filter { hint ->
                    validTrackedSlots.contains(hint.roomDbId to hint.itemOwnerId)
                }

                _hintsByYou.value = rawByYou.filter { hint ->
                    validTrackedSlots.contains(hint.roomDbId to hint.locationOwnerId)
                }

            } catch (e: Exception) {
                errorMessage.value = "History Refresh failed: ${e.message}"
                Log.e("HistoryViewModel", "Error during full history refresh", e)
            } finally {
                isLoading.value = false
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

    private fun saveViewPreferences(
        showFinished: Boolean? = null,
        showFoundHints: Boolean? = null
    ) {
        viewModelScope.launch {
            try {
                val request = com.jones.aptracker.network.UpdateGlobalPrefsRequest(
                    ui_show_finished = showFinished,
                    ui_show_found_hints = showFoundHints
                )
                RetrofitClient.instance.updateUserPreferences(request)
            } catch (e: Exception) {
                Log.e("HistoryViewModel", "Failed to save view preferences", e)
            }
        }
    }
}

data class PlayerDisplayInfo(
    val originalName: String,
    val alias: String?
) : Comparable<PlayerDisplayInfo> {
    override fun compareTo(other: PlayerDisplayInfo): Int {
        return this.originalName.compareTo(other.originalName)
    }
}