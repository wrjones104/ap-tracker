package com.jones.aptracker.ui

import android.app.Application
import android.content.Context
import android.util.Log
import androidx.compose.runtime.mutableStateOf
import androidx.core.content.edit
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
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import retrofit2.HttpException

// --- 1. FILTER INTERFACE ---
sealed interface HistoryFilter {
    object Active : HistoryFilter
    object Archived : HistoryFilter
    object All : HistoryFilter
    data class Specific(val roomId: Int) : HistoryFilter
}

class HistoryViewModel(application: Application) : AndroidViewModel(application) {

    private val repository: HistoryRepository
    private val userRepository: UserRepository

    // SharedPreferences for local UI settings
    private val prefs = application.getSharedPreferences("ap_tracker_prefs", Context.MODE_PRIVATE)

    private val _itemHistory = MutableStateFlow<List<HistoryItem>>(emptyList())
    val itemHistory: StateFlow<List<HistoryItem>> = _itemHistory

    private val _roomNames = MutableStateFlow<Map<Int, String>>(emptyMap())
    val roomNames: StateFlow<Map<Int, String>> = _roomNames

    // --- 2. STATE FLOWS ---
    private val _activeRoomIds = MutableStateFlow<Set<Int>>(emptySet())
    val activeRoomIds: StateFlow<Set<Int>> = _activeRoomIds

    private val _archivedRoomIds = MutableStateFlow<Set<Int>>(emptySet())
    val archivedRoomIds: StateFlow<Set<Int>> = _archivedRoomIds

    // Default filter is now ACTIVE
    private val _historyFilter = MutableStateFlow<HistoryFilter>(HistoryFilter.Active)
    val historyFilter: StateFlow<HistoryFilter> = _historyFilter

    val availableRooms: StateFlow<List<Pair<Int, String>>> = combine(_roomNames, _activeRoomIds) { names, activeIds ->
        names.filterKeys { it in activeIds }
            .toList()
            .sortedBy { it.second }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val searchQuery = mutableStateOf("")
    val isLoading = MutableStateFlow(true)
    val errorMessage = mutableStateOf<String?>(null)

    // --- Toggles ---
    private val _showFoundHints = MutableStateFlow(false)
    val showFoundHints: StateFlow<Boolean> = _showFoundHints

    private val _showFinished = MutableStateFlow(true)
    val showFinished: StateFlow<Boolean> = _showFinished

    private val _showProgression = MutableStateFlow(true)
    val showProgression: StateFlow<Boolean> = _showProgression

    private val _showUseful = MutableStateFlow(true)
    val showUseful: StateFlow<Boolean> = _showUseful

    // Initialize from SharedPreferences (Default to false/OFF)
    private val _useCondensed = MutableStateFlow(prefs.getBoolean("ui_use_condensed", false))
    val useCondensed: StateFlow<Boolean> = _useCondensed

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

    val availablePlayers: StateFlow<List<PlayerDisplayInfo>> = combine(
        _itemHistory,
        _historyFilter,
        _activeRoomIds,
        _archivedRoomIds
    ) { history, filter, activeIds, archivedIds ->
        history
            .filter { item ->
                when (filter) {
                    is HistoryFilter.Active -> item.db_id in activeIds
                    is HistoryFilter.Archived -> item.db_id in archivedIds
                    is HistoryFilter.All -> true
                    is HistoryFilter.Specific -> item.db_id == filter.roomId
                }
            }
            .groupBy { it.playerName }
            .map { (name, items) ->
                val bestAlias = items.firstNotNullOfOrNull { it.playerAlias }
                PlayerDisplayInfo(name, bestAlias)
            }
            .sorted()
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    // --- HINTS PIPELINE ---
    // Reactive valid slots flow instead of static variable
    private val _validTrackedSlots = MutableStateFlow<Set<Pair<Int, Int>>>(emptySet())
    val validTrackedSlots: StateFlow<Set<Pair<Int, Int>>> = _validTrackedSlots

    // Reactive Hint flows matching the toggle + DB flow
    val hintsForYou: StateFlow<List<HintEntity>> = combine(
        _historyFilter,
        _showFoundHints,
        _validTrackedSlots
    ) { filter, showFound, validSlots ->
        Triple(filter, showFound, validSlots)
    }.flatMapLatest { (filter, showFound, validSlots) ->
        val sourceFlow = when (filter) {
            is HistoryFilter.Specific -> repository.getHintsForRoom(filter.roomId, "for_you")
            else -> repository.getGlobalHints("for_you")
        }

        sourceFlow.map { hintList ->
            hintList.filter { hint ->
                (showFound || !hint.isFound) && validSlots.contains(hint.roomDbId to hint.itemOwnerId)
            }
        }
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5000),
        initialValue = emptyList()
    )

    val hintsByYou: StateFlow<List<HintEntity>> = combine(
        _historyFilter,
        _showFoundHints,
        _validTrackedSlots
    ) { filter, showFound, validSlots ->
        Triple(filter, showFound, validSlots)
    }.flatMapLatest { (filter, showFound, validSlots) ->
        val sourceFlow = when (filter) {
            is HistoryFilter.Specific -> repository.getHintsForRoom(filter.roomId, "by_you")
            else -> repository.getGlobalHints("by_you")
        }

        sourceFlow.map { hintList ->
            hintList.filter { hint ->
                (showFound || !hint.isFound) && validSlots.contains(hint.roomDbId to hint.locationOwnerId)
            }
        }
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5000),
        initialValue = emptyList()
    )

    val availableHintPlayers: StateFlow<List<PlayerDisplayInfo>> = combine(
        hintsForYou,
        hintsByYou,
        _historyFilter,
        _activeRoomIds,
        _archivedRoomIds
    ) { forYou, byYou, filter, activeIds, archivedIds ->

        fun shouldShow(roomId: Int?): Boolean {
            if (roomId == null) return true // Global items
            return when (filter) {
                is HistoryFilter.Active -> roomId in activeIds
                is HistoryFilter.Archived -> roomId in archivedIds
                is HistoryFilter.All -> true
                is HistoryFilter.Specific -> roomId == filter.roomId
            }
        }

        val relevantForYou = forYou.filter { shouldShow(it.roomDbId) }
        val relevantByYou = byYou.filter { shouldShow(it.roomDbId) }

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
        _selectedPlayerFilter.value = null
        searchQuery.value = ""

        if (roomId != null) {
            _historyFilter.value = HistoryFilter.Specific(roomId)
        } else {
            _historyFilter.value = HistoryFilter.Active
        }

        Log.d("HistoryViewModel", "Loading history for Room ID: ${roomId ?: "Global"}")
        refreshAllHistory()
    }

    fun setHistoryFilter(filter: HistoryFilter) {
        _historyFilter.value = filter
        _selectedPlayerFilter.value = null
    }

    private fun fetchUserPreferences() {
        viewModelScope.launch {
            try {
                val profile = RetrofitClient.instance.getUserProfile()
                // We no longer sync condensed preference from API for the UI view
                _showFinished.value = profile.ui_show_finished_default
                _showFoundHints.value = profile.ui_show_found_hints_default
            } catch (e: Exception) {
                Log.e("HistoryViewModel", "Failed to load user profile for settings", e)
            }
        }
    }

    // --- TOGGLE SETTERS ---

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

            // The reactive combine flow above automatically handles the UI update locally!
            // But we launch a silent background request here to fetch any new hints from the API
            viewModelScope.launch {
                repository.refreshHintHistory(currentRoomId, show)
            }
        }
    }

    fun setShowProgression(show: Boolean) {
        _showProgression.value = show
        // Note: Not saving these to API/Prefs yet, but could be added to saveViewPreferences if desired
    }

    fun setShowUseful(show: Boolean) {
        _showUseful.value = show
    }

    fun setUseCondensed(use: Boolean) {
        if (_useCondensed.value != use) {
            _useCondensed.value = use
            // Save to SharedPreferences using KTX
            prefs.edit {
                putBoolean("ui_use_condensed", use)
            }
        }
    }

    fun refreshAllHistory() {
        Log.d("HistoryViewModel", "Triggering refresh for Room ID: ${currentRoomId ?: "Global"}")
        viewModelScope.launch {
            isLoading.value = true
            errorMessage.value = null

            try {
                // --- STEP 1: Metadata & Room Setup (Fast) ---
                val trackedRooms = RetrofitClient.instance.getUserTrackedSlots()

                val aliasMap = mutableMapOf<Pair<Int, Int>, String>()
                val liveFinishedSlots = mutableSetOf<Pair<Int, Int>>()
                val liveIcons = mutableMapOf<Int, String>()
                val finishedPlayerNames = mutableSetOf<Pair<Int, String>>()
                val roomNameMap = mutableMapOf<Int, String>()
                val validSlotsSet = mutableSetOf<Pair<Int, Int>>()

                val activeIds = mutableSetOf<Int>()
                val archivedIds = mutableSetOf<Int>()

                trackedRooms.forEach { room ->
                    if (room.is_archived) {
                        archivedIds.add(room.room_db_id)
                    } else {
                        activeIds.add(room.room_db_id)
                    }

                    liveIcons[room.room_db_id] = room.icon_name
                    roomNameMap[room.room_db_id] = room.room_alias

                    room.tracked_slots.forEach { slot ->
                        validSlotsSet.add(room.room_db_id to slot.slot_id)

                        if (!slot.player_alias.isNullOrBlank()) {
                            aliasMap[room.room_db_id to slot.slot_id] = slot.player_alias
                        }
                        if (slot.is_finished) {
                            liveFinishedSlots.add(room.room_db_id to slot.slot_id)
                            finishedPlayerNames.add(room.room_db_id to slot.player_name)
                        }
                    }
                }

                _roomNames.value = roomNameMap
                _validTrackedSlots.value = validSlotsSet
                _liveAliases.value = aliasMap
                _confirmedFinishedPlayers.value = finishedPlayerNames
                _activeRoomIds.value = activeIds
                _archivedRoomIds.value = archivedIds

                // --- STEP 2: Item History (Priority 1) ---
                repository.refreshItemHistory()

                val rawItemEntities = if (currentRoomId != null) {
                    repository.getHistoryForRoom(currentRoomId!!)
                } else {
                    repository.getGlobalHistory()
                }

                _itemHistory.value = rawItemEntities.mapNotNull { entity ->
                    if (entity.roomId != null && entity.slot_id != null) {
                        if (!validSlotsSet.contains(entity.roomId to entity.slot_id)) {
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

                // --- STEP 3: UNBLOCK UI HERE ---
                // The Item list is ready. Let the user see it immediately!
                isLoading.value = false

                // --- STEP 4: Hint History (Background Priority) ---
                // We launch this in a separate non-blocking way (or just sequentially after flipping the flag)
                // The UI will update automatically via Flows when this finishes.
                try {
                    val includeFound = _showFoundHints.value
                    repository.refreshHintHistory(currentRoomId, includeFound)
                } catch (e: Exception) {
                    Log.e("HistoryViewModel", "Background hint refresh failed", e)
                    // We don't show an error message to the user here because
                    // the main content (Items) loaded successfully.
                }

            } catch (e: Exception) {
                errorMessage.value = "History Refresh failed: ${e.message}"
                Log.e("HistoryViewModel", "Error during full history refresh", e)
                isLoading.value = false // Ensure loading stops on error
            }
        }
    }

    fun onSearchQueryChanged(query: String) { searchQuery.value = query }
    fun clearErrorMessage() { errorMessage.value = null }
    fun clearActionMessage() { _actionMessage.value = null }

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

    private fun saveViewPreferences(
        showFinished: Boolean? = null,
        showFoundHints: Boolean? = null
    ) {
        viewModelScope.launch {
            try {
                val params = mutableMapOf<String, Boolean>()
                showFinished?.let { params["ui_show_finished"] = it }
                showFoundHints?.let { params["ui_show_found_hints"] = it }
                // No longer sending use_condensed_messages to API

                if (params.isNotEmpty()) {
                    RetrofitClient.instance.updateUserPreferences(params)
                }
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