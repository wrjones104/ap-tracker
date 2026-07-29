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

    private val _trackedPlayers = MutableStateFlow<List<TrackedPlayer>>(emptyList())

    private val _roomNames = MutableStateFlow<Map<Int, String>>(emptyMap())
    val roomNames: StateFlow<Map<Int, String>> = _roomNames

    // --- 2. STATE FLOWS ---
    private val _activeRoomIds = MutableStateFlow<Set<Int>>(emptySet())
    val activeRoomIds: StateFlow<Set<Int>> = _activeRoomIds

    private val _archivedRoomIds = MutableStateFlow<Set<Int>>(emptySet())
    val archivedRoomIds: StateFlow<Set<Int>> = _archivedRoomIds

    private val _roomIcons = MutableStateFlow<Map<Int, String>>(emptyMap())
    val roomIcons: StateFlow<Map<Int, String>> = _roomIcons

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

    // --- Pagination ---
    private var currentPageOffset = 0
    private val PAGE_SIZE = 50
    private var isAllDataLoaded = false
    private val _isNextPageLoading = MutableStateFlow(false)
    val isNextPageLoading: StateFlow<Boolean> = _isNextPageLoading

    // --- Toggles ---
    private val _showFoundHints = MutableStateFlow(false)
    val showFoundHints: StateFlow<Boolean> = _showFoundHints

    private val _showFinished = MutableStateFlow(true)
    val showFinished: StateFlow<Boolean> = _showFinished

    private val _showProgression = MutableStateFlow(true)
    val showProgression: StateFlow<Boolean> = _showProgression

    private val _showUseful = MutableStateFlow(true)
    val showUseful: StateFlow<Boolean> = _showUseful

    private val _showFiller = MutableStateFlow(false)
    val showFiller: StateFlow<Boolean> = _showFiller

    private val _showTrap = MutableStateFlow(false)
    val showTrap: StateFlow<Boolean> = _showTrap

    // Initialize from SharedPreferences (Default to false/OFF)
    private val _useCondensed = MutableStateFlow(prefs.getBoolean("ui_use_condensed", false))
    val useCondensed: StateFlow<Boolean> = _useCondensed

    // Add toggle for Ignored Items (Default to false/OFF)
    private val _showIgnoredItems = MutableStateFlow(prefs.getBoolean("ui_show_ignored_items", false))
    val showIgnoredItems: StateFlow<Boolean> = _showIgnoredItems

    private val _selectedItemGroups = MutableStateFlow<List<String>>(emptyList())
    val selectedItemGroups: StateFlow<List<String>> = _selectedItemGroups

    private val _isFetchingGroups = MutableStateFlow(false)
    val isFetchingGroups: StateFlow<Boolean> = _isFetchingGroups

    private val groupsCache = mutableMapOf<Triple<String, String, Int?>, List<String>>()

    private var fetchGroupsJob: kotlinx.coroutines.Job? = null
    private var latestGroupQuery: Triple<String, String, Int?>? = null

    private val _liveAliases = MutableStateFlow<Map<Pair<Int, Int>, String>>(emptyMap())
    private val _confirmedFinishedPlayers = MutableStateFlow<Set<Pair<Int, String>>>(emptySet())

    val finishedPlayerKeys: StateFlow<Set<Pair<Int, String>>> = combine(_itemHistory, _confirmedFinishedPlayers) { history, confirmed ->
        val fromHistory = history
            .filter { it.isPlayerFinished && it.room_db_id != null }
            .map { it.room_db_id!! to it.playerName }
            .toSet()

        fromHistory + confirmed
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptySet())

    private var currentRoomId: Int? = null

    private val _selectedPlayerFilter = MutableStateFlow<String?>(null)
    val selectedPlayerFilter: StateFlow<String?> = _selectedPlayerFilter

    val availablePlayers: StateFlow<List<PlayerDisplayInfo>> = combine(
        _trackedPlayers,
        _historyFilter,
        _activeRoomIds,
        _archivedRoomIds
    ) { trackedPlayers, filter, activeIds, archivedIds ->
        trackedPlayers
            .filter { player ->
                when (filter) {
                    is HistoryFilter.Active -> player.roomId in activeIds
                    is HistoryFilter.Archived -> player.roomId in archivedIds
                    is HistoryFilter.All -> true
                    is HistoryFilter.Specific -> player.roomId == filter.roomId
                }
            }
            .groupBy { player -> player.playerName }
            .map { (name, players) ->
                val bestAlias = players.firstNotNullOfOrNull { it.playerAlias }
                val backfillNeeded = players.any { it.needsBackfill }
                PlayerDisplayInfo(name, bestAlias, backfillNeeded)
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

    private val _pendingNavigateToActivity = MutableStateFlow(false)
    val pendingNavigateToActivity: StateFlow<Boolean> = _pendingNavigateToActivity

    fun triggerNavigateToActivity() {
        _pendingNavigateToActivity.value = true
    }

    fun clearPendingNavigateToActivity() {
        _pendingNavigateToActivity.value = false
    }

    init {
        val db = AppDatabase.getInstance(application)
        val historyDao = db.historyDao()
        val hintDao = db.hintDao()

        val apiService = RetrofitClient.instance
        repository = HistoryRepository(apiService, historyDao, hintDao, application)
        userRepository = UserRepository(apiService)
        fetchUserPreferences()
    }

    fun loadHistoryFor(roomId: Int?, initialSearchQuery: String? = null, initialPlayerFilter: String? = null) {
        currentRoomId = roomId
        _selectedPlayerFilter.value = initialPlayerFilter
        searchQuery.value = initialSearchQuery ?: ""

        if (roomId != null) {
            _historyFilter.value = HistoryFilter.Specific(roomId)
        } else {
            _historyFilter.value = HistoryFilter.Active
        }

        Log.d("HistoryViewModel", "Loading history for Room ID: ${roomId ?: "Global"}")
        
        // Clear current items while loading new context
        _itemHistory.value = emptyList()
        
        refreshAllHistory()
    }

    fun setHistoryFilter(filter: HistoryFilter) {
        _historyFilter.value = filter
        _selectedPlayerFilter.value = null
        currentRoomId = when (filter) {
            is HistoryFilter.Specific -> filter.roomId
            else -> null
        }
        reloadHistory()
    }

    fun reloadHistory(showSpinner: Boolean = true) {
        viewModelScope.launch {
            if (showSpinner) {
                isLoading.value = true
            }
            errorMessage.value = null
            try {
                currentPageOffset = 0
                isAllDataLoaded = true // All local data loaded in one shot
                val rawItemEntities = when (val filter = _historyFilter.value) {
                    is HistoryFilter.Specific -> {
                        repository.getHistoryForRoom(filter.roomId)
                    }
                    else -> {
                        repository.getGlobalHistory()
                    }
                }
                
                _itemHistory.value = mapEntitiesToHistoryItems(rawItemEntities)
                currentPageOffset = rawItemEntities.size
            } catch (e: Exception) {
                errorMessage.value = "Failed to load history: ${e.message}"
                Log.e("HistoryViewModel", "Error reloading history", e)
            } finally {
                if (showSpinner) {
                    isLoading.value = false
                }
            }
        }
    }

    private fun fetchUserPreferences() {
        viewModelScope.launch {
            try {
                val profile = RetrofitClient.instance.getUserProfile()
                // We no longer sync condensed preference from API for the UI view
                _showFinished.value = profile.ui_show_finished_default
                _showFoundHints.value = profile.ui_show_found_hints_default
                _showProgression.value = profile.ui_show_progression_default
                _showUseful.value = profile.ui_show_useful_default
                _showFiller.value = profile.ui_show_filler_default
                _showTrap.value = profile.ui_show_trap_default
            } catch (e: Exception) {
                Log.e("HistoryViewModel", "Failed to load user profile for settings", e)
            }
        }
    }

    fun setShowIgnoredItems(show: Boolean) {
        if (_showIgnoredItems.value != show) {
            _showIgnoredItems.value = show
            prefs.edit {
                putBoolean("ui_show_ignored_items", show)
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
                repository.refreshHintHistory(currentRoomId)
            }
        }
    }

    fun setShowProgression(show: Boolean) {
        if (_showProgression.value != show) {
            _showProgression.value = show
            saveViewPreferences(showProgression = show)
        }
    }

    fun setShowUseful(show: Boolean) {
        if (_showUseful.value != show) {
            _showUseful.value = show
            saveViewPreferences(showUseful = show)
        }
    }
    
    fun setShowFiller(show: Boolean) {
        if (_showFiller.value != show) {
            _showFiller.value = show
            saveViewPreferences(showFiller = show)
        }
    }

    fun setShowTrap(show: Boolean) {
        if (_showTrap.value != show) {
            _showTrap.value = show
            saveViewPreferences(showTrap = show)
        }
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
                val trackedPlayersList = mutableListOf<TrackedPlayer>()

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

                        trackedPlayersList.add(
                            TrackedPlayer(
                                roomId = room.room_db_id,
                                playerName = slot.player_name,
                                playerAlias = slot.player_alias,
                                needsBackfill = slot.needs_backfill
                            )
                        )

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
                _roomIcons.value = liveIcons
                _trackedPlayers.value = trackedPlayersList

                // --- STEP 1.5: Re-align currentRoomId if the room's server database ID changed ---
                var targetRoomId = currentRoomId
                if (targetRoomId != null) {
                    val syncPrefs = getApplication<Application>().getSharedPreferences("ap_tracker_sync_watermarks", Context.MODE_PRIVATE)
                    val migratedId = syncPrefs.getInt("room_id_migration_${targetRoomId}", -1)
                    if (migratedId != -1) {
                        Log.d("HistoryViewModel", "Updating currentRoomId from $targetRoomId to $migratedId due to shared migration record.")
                        currentRoomId = migratedId
                        if (_historyFilter.value is HistoryFilter.Specific) {
                            _historyFilter.value = HistoryFilter.Specific(migratedId)
                        }
                    } else {
                        val db = AppDatabase.getInstance(getApplication())
                        val currentRoomEntity = db.roomDao().getAllRoomsOneShot().find { it.id == targetRoomId }
                        if (currentRoomEntity != null) {
                            val matchingServerRoom = trackedRooms.find { it.room_id == currentRoomEntity.room_id }
                            if (matchingServerRoom != null && matchingServerRoom.room_db_id != targetRoomId) {
                                Log.d("HistoryViewModel", "Updating currentRoomId from $targetRoomId to ${matchingServerRoom.room_db_id} due to server re-alignment.")
                                currentRoomId = matchingServerRoom.room_db_id
                                if (_historyFilter.value is HistoryFilter.Specific) {
                                    _historyFilter.value = HistoryFilter.Specific(matchingServerRoom.room_db_id)
                                }
                            }
                        }
                    }
                }

                // --- STEP 2: Load cached history and manage loading state ---
                reloadHistory()
                val hasLocalItems = itemHistory.value.isNotEmpty()
                if (hasLocalItems) {
                    isLoading.value = false
                }

                // --- STEP 3: Background delta sync with real-time UI streaming ---
                try {
                    repository.syncHistoryBatch(trackedRooms) {
                        reloadHistory(showSpinner = false)
                    }
                    reloadHistory(showSpinner = false)
                } catch (e: Exception) {
                    Log.e("HistoryViewModel", "Background sync failed", e)
                } finally {
                    isLoading.value = false
                }

            } catch (e: Exception) {
                errorMessage.value = "History Refresh failed: ${e.message}"
                Log.e("HistoryViewModel", "Error during full history refresh", e)
                isLoading.value = false // Ensure loading stops on error
            }
        }
    }

    fun loadNextPage() {
        if (isAllDataLoaded || _isNextPageLoading.value) return

        viewModelScope.launch {
            _isNextPageLoading.value = true
            try {
                Log.d("HistoryViewModel", "Loading next page of history at offset $currentPageOffset for room: $currentRoomId")
                val nextEntities = if (currentRoomId != null) {
                    repository.getHistoryForRoomPaged(currentRoomId!!, PAGE_SIZE, currentPageOffset)
                } else {
                    repository.getGlobalHistoryPaged(PAGE_SIZE, currentPageOffset)
                }
                
                if (nextEntities.isEmpty()) {
                    isAllDataLoaded = true
                } else {
                    val mappedNext = mapEntitiesToHistoryItems(nextEntities)
                    _itemHistory.value = (_itemHistory.value + mappedNext).distinctBy { it.id }
                    currentPageOffset += nextEntities.size
                    if (nextEntities.size < PAGE_SIZE) {
                        isAllDataLoaded = true
                    }
                }
            } catch (e: Exception) {
                Log.e("HistoryViewModel", "Failed to load next history page", e)
            } finally {
                _isNextPageLoading.value = false
            }
        }
    }

    private fun mapEntitiesToHistoryItems(entities: List<com.jones.aptracker.network.HistoryItemEntity>): List<HistoryItem> {
        val validSlotsSet = _validTrackedSlots.value
        val liveAliases = _liveAliases.value
        val liveIcons = _roomIcons.value
        val confirmedFinished = _confirmedFinishedPlayers.value
        
        var filteredCount = 0
        val result = entities.mapNotNull { entity ->
            if (entity.roomId != null && entity.slot_id != null) {
                if (!validSlotsSet.contains(entity.roomId to entity.slot_id)) {
                    filteredCount++
                    return@mapNotNull null
                }
            }

            val liveAlias = if (entity.roomId != null && entity.slot_id != null) {
                liveAliases[entity.roomId to entity.slot_id]
            } else null

            val liveIcon = if (entity.roomId != null) {
                liveIcons[entity.roomId]
            } else null

            val isActuallyFinished = entity.isPlayerFinished ||
                    (entity.roomId != null && entity.slot_id != null &&
                            confirmedFinished.contains(entity.roomId to entity.playerName))

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
                room_db_id = entity.roomId,
                host = entity.host,
                receivingGame = entity.receivingGame,
                senderName = entity.senderName,
                senderAlias = entity.senderAlias,
                senderGame = entity.senderGame,
                locationName = entity.locationName,
                receivedCount = entity.receivedCount
            )
        }
        return result
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

    fun fetchGroupsForItem(gameName: String, itemName: String, roomDbId: Int?) {
        fetchGroupsJob?.cancel()
        val queryKey = Triple(gameName, itemName, roomDbId)
        latestGroupQuery = queryKey

        val cacheKey = Triple(gameName, itemName, roomDbId)
        val cached = groupsCache[cacheKey]
        if (cached != null) {
            _selectedItemGroups.value = cached
            _isFetchingGroups.value = false
            return
        }

        _selectedItemGroups.value = emptyList()
        _isFetchingGroups.value = true
        fetchGroupsJob = viewModelScope.launch {
            try {
                val groups = RetrofitClient.instance.getItemGroups(gameName, itemName, roomDbId)
                    .filter { !it.equals("Everything", ignoreCase = true) && !it.equals("Everywhere", ignoreCase = true) }
                if (latestGroupQuery == queryKey) {
                    groupsCache[cacheKey] = groups
                    _selectedItemGroups.value = groups
                }
            } catch (e: Exception) {
                Log.e("HistoryViewModel", "Failed to fetch groups for item $itemName in game $gameName", e)
            } finally {
                if (latestGroupQuery == queryKey) {
                    _isFetchingGroups.value = false
                }
            }
        }
    }

    fun clearSelectedGroups() {
        latestGroupQuery = null
        fetchGroupsJob?.cancel()
        _selectedItemGroups.value = emptyList()
        _isFetchingGroups.value = false
    }

    fun ignoreItemGroup(groupName: String, gameName: String) {
        viewModelScope.launch {
            try {
                val request = com.jones.aptracker.network.AddIgnoreItemRequest(
                    itemName = groupName,
                    gameName = gameName,
                    isGroup = true
                )
                RetrofitClient.instance.addIgnoreItem(request)
                _actionMessage.value = "Ignored group '$groupName'"
            } catch (e: HttpException) {
                if (e.code() == 409) {
                    errorMessage.value = "Group '$groupName' is already ignored for this game."
                } else {
                    Log.e("HistoryViewModel", "Failed to ignore item group (HTTP ${e.code()})", e)
                    errorMessage.value = "Failed to ignore item group."
                }
            } catch (e: Exception) {
                Log.e("HistoryViewModel", "Failed to ignore item group", e)
                errorMessage.value = "Failed to ignore item group. Check connection."
            }
        }
    }

    private fun saveViewPreferences(
        showFinished: Boolean? = null,
        showFoundHints: Boolean? = null,
        showProgression: Boolean? = null,
        showUseful: Boolean? = null,
        showFiller: Boolean? = null,
        showTrap: Boolean? = null
    ) {
        viewModelScope.launch {
            try {
                val params = mutableMapOf<String, Boolean>()
                showFinished?.let { params["ui_show_finished"] = it }
                showFoundHints?.let { params["ui_show_found_hints"] = it }
                showProgression?.let { params["ui_show_progression"] = it }
                showUseful?.let { params["ui_show_useful"] = it }
                showFiller?.let { params["ui_show_filler"] = it }
                showTrap?.let { params["ui_show_trap"] = it }
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
    val alias: String?,
    val needsBackfill: Boolean = false
) : Comparable<PlayerDisplayInfo> {
    override fun compareTo(other: PlayerDisplayInfo): Int {
        return this.originalName.compareTo(other.originalName)
    }
}

data class TrackedPlayer(
    val roomId: Int,
    val playerName: String,
    val playerAlias: String?,
    val needsBackfill: Boolean = false
)