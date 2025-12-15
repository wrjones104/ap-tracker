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
import com.jones.aptracker.repository.HistoryRepository
import com.jones.aptracker.repository.UserRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import retrofit2.HttpException

class HistoryViewModel(application: Application) : AndroidViewModel(application) {

    private val repository: HistoryRepository
    private val userRepository: UserRepository

    private val _itemHistory = MutableStateFlow<List<HistoryItem>>(emptyList())
    val itemHistory: StateFlow<List<HistoryItem>> = _itemHistory

    private val _roomNames = MutableStateFlow<Map<Int, String>>(emptyMap())
    val roomNames: StateFlow<Map<Int, String>> = _roomNames

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
    private val _liveAliases = MutableStateFlow<Map<Pair<Int, Int>, String>>(emptyMap())

    private val _confirmedFinishedPlayers = MutableStateFlow<Set<Pair<Int, String>>>(emptySet())

    val finishedPlayerKeys: StateFlow<Set<Pair<Int, String>>> = combine(_itemHistory, _confirmedFinishedPlayers) { history, confirmed ->
        val fromHistory = history
            .filter { it.isPlayerFinished && it.db_id != null }
            .map { it.db_id!! to it.playerName }
            .toSet()

        fromHistory + confirmed
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptySet())

    private var currentRoomId: Int? = null

    private val _selectedPlayerFilter = MutableStateFlow<String?>(null)
    val selectedPlayerFilter: StateFlow<String?> = _selectedPlayerFilter

    private val _selectedRoomFilter = MutableStateFlow<Int?>(null)
    val selectedRoomFilter: StateFlow<Int?> = _selectedRoomFilter

    // 2. Helper to get Room List (Derived from the roomNames map we already built)
    val availableRooms: StateFlow<List<Pair<Int, String>>> = _roomNames.map { map ->
        map.toList().sortedBy { it.second }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    // 3. Update 'availablePlayers' to respect the selected Room
    val availablePlayers: StateFlow<List<PlayerDisplayInfo>> = combine(
        _itemHistory,
        _selectedRoomFilter
    ) { history, selectedRoomId ->
        history
            .filter { item ->
                currentRoomId != null || selectedRoomId == null || item.db_id == selectedRoomId
            }
            .groupBy { it.playerName }
            .map { (name, items) ->
                val bestAlias = items.firstNotNullOfOrNull { it.playerAlias }
                PlayerDisplayInfo(name, bestAlias)
            }
            .sorted()
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val availableHintPlayers: StateFlow<List<PlayerDisplayInfo>> = combine(
        _hintsForYou,
        _hintsByYou,
        _selectedRoomFilter
    ) { forYou, byYou, selectedRoomId ->

        // Determine effective filter ID
        val effectiveRoomFilter = if (currentRoomId != null) null else selectedRoomId

        val relevantForYou = if (effectiveRoomFilter == null) forYou else forYou.filter { it.roomDbId == effectiveRoomFilter }
        val relevantByYou = if (effectiveRoomFilter == null) byYou else byYou.filter { it.roomDbId == effectiveRoomFilter }

        val allMentions = (relevantForYou.map { PlayerDisplayInfo(it.itemOwnerName, it.itemOwnerAlias) } +
                relevantByYou.map { PlayerDisplayInfo(it.locationOwnerName, it.locationOwnerAlias) })

        allMentions
            .groupBy { it.originalName }
            .map { (name, mentions) ->
                val bestAlias = mentions.firstNotNullOfOrNull { it.alias }
                PlayerDisplayInfo(name, bestAlias)
            }
            .sorted()
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

        // RESET FILTERS on navigation to prevent stale state
        _selectedRoomFilter.value = null
        _selectedPlayerFilter.value = null
        searchQuery.value = ""

        Log.d("HistoryViewModel", "Loading history for Room ID: ${roomId ?: "Global"}")
        refreshAllHistory()
    }

    fun onRoomFilterSelected(roomId: Int?) {
        _selectedRoomFilter.value = roomId
        _selectedPlayerFilter.value = null
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

    fun setUseCondensed(use: Boolean) {
        _useCondensed.value = use
    }

    fun refreshAllHistory() {
        Log.d("HistoryViewModel", "Triggering refresh for Room ID: ${currentRoomId ?: "Global"}")
        viewModelScope.launch {
            isLoading.value = true
            errorMessage.value = null

            try {
                // 1. Fetch latest tracking config from API
                val trackedRooms = RetrofitClient.instance.getUserTrackedSlots()

                // 2. Build Lookup Maps for "Live" Data
                val aliasMap = mutableMapOf<Pair<Int, Int>, String>()
                val liveFinishedSlots = mutableSetOf<Pair<Int, Int>>()
                val liveIcons = mutableMapOf<Int, String>()
                val finishedPlayerNames = mutableSetOf<Pair<Int, String>>()
                val roomNameMap = mutableMapOf<Int, String>()
                val validSlotsSet = mutableSetOf<Pair<Int, Int>>()

                trackedRooms.forEach { room ->
                    // --- Skip Archived Rooms ---
                    if (room.is_archived) return@forEach

                    liveIcons[room.room_db_id] = room.icon_name
                    roomNameMap[room.room_db_id] = room.room_alias

                    room.tracked_slots.forEach { slot ->
                        // Track valid slots
                        validSlotsSet.add(room.room_db_id to slot.slot_id)

                        // Store Live Alias
                        if (!slot.player_alias.isNullOrBlank()) {
                            aliasMap[room.room_db_id to slot.slot_id] = slot.player_alias
                        }

                        // Store Finished Status
                        if (slot.is_finished) {
                            liveFinishedSlots.add(room.room_db_id to slot.slot_id)
                            finishedPlayerNames.add(room.room_db_id to slot.player_name)
                        }
                    }
                }

                // Update StateFlows (This now excludes archived rooms)
                _roomNames.value = roomNameMap
                validTrackedSlots = validSlotsSet
                _liveAliases.value = aliasMap
                _confirmedFinishedPlayers.value = finishedPlayerNames

                // 3. Refresh & Fetch Item History
                repository.refreshItemHistory()

                val rawItemEntities = if (currentRoomId != null) {
                    repository.getHistoryForRoom(currentRoomId!!)
                } else {
                    repository.getGlobalHistory()
                }

                // 4. Map DB Entities to UI Models
                _itemHistory.value = rawItemEntities.mapNotNull { entity ->
                    // Filter out slots we stopped tracking (includes slots from archived rooms)
                    if (entity.roomId != null && entity.slot_id != null) {
                        if (!validTrackedSlots.contains(entity.roomId to entity.slot_id)) {
                            return@mapNotNull null
                        }
                    }

                    val liveAlias = if (entity.roomId != null && entity.slot_id != null) {
                        _liveAliases.value[entity.roomId to entity.slot_id]
                    } else null

                    val liveIcon = if (entity.roomId != null) {
                        liveIcons[entity.roomId]
                    } else null

                    val isActuallyFinished = entity.isPlayerFinished ||
                            (entity.roomId != null && entity.slot_id != null &&
                                    liveFinishedSlots.contains(entity.roomId to entity.slot_id))

                    HistoryItem(
                        id = entity.id,
                        playerName = entity.playerName,
                        playerAlias = liveAlias ?: entity.playerAlias,
                        itemName = entity.itemName,
                        isPlayerFinished = isActuallyFinished,
                        itemFlags = entity.itemFlags,
                        timestamp = entity.timestamp,
                        tracker_id = entity.tracker_id,
                        slot_id = entity.slot_id,
                        icon_name = liveIcon ?: entity.icon_name,
                        db_id = entity.roomId,
                        host = entity.host,
                        receivingGame = entity.receivingGame,
                        senderName = entity.senderName,
                        senderAlias = entity.senderAlias,
                        senderGame = entity.senderGame,
                        locationName = entity.locationName
                    )
                }

                // 5. Handle Hints
                val includeFound = _showFoundHints.value
                repository.refreshHintHistory(currentRoomId, includeFound)

                val (rawForYou, rawByYou) = if (currentRoomId != null) {
                    repository.getHintsForRoom(currentRoomId!!, includeFound)
                } else {
                    repository.getGlobalHints(includeFound)
                }

                // Filtering hints using validTrackedSlots automatically excludes archived rooms
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