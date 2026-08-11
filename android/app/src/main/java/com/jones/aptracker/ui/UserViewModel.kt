package com.jones.aptracker.ui

import android.app.Application
import android.content.Context
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.data.SettingsManager
import com.jones.aptracker.network.CheeseAuthRequest
import com.jones.aptracker.network.CheeseSlotState
import com.jones.aptracker.network.UpdateCheesePingRequest
import com.jones.aptracker.network.IgnoreItem
import com.jones.aptracker.network.WhitelistItem
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.RoomWithTrackedSlots
import com.jones.aptracker.network.UpdateSlotPrefsRequest
import com.jones.aptracker.network.UserProfile
import com.jones.aptracker.network.SnoozeRequest
import com.jones.aptracker.network.AutocompleteOption
import com.jones.aptracker.network.ThresholdGroup
import com.jones.aptracker.network.CreateThresholdGroupRequest
import com.jones.aptracker.network.ThresholdGroupItemRequest
import com.jones.aptracker.network.MilestoneTemplate
import com.jones.aptracker.network.CreateMilestoneTemplateRequest
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.database.CachedDatapackageEntity
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.jones.aptracker.repository.HistoryRepository
import com.jones.aptracker.repository.UserRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import retrofit2.HttpException
import java.time.Instant
import java.time.temporal.ChronoUnit

class UserViewModel(application: Application) : AndroidViewModel(application) {

    // --- Dependencies ---
    private val settingsManager = SettingsManager(application)
    private val userRepository = UserRepository(RetrofitClient.instance)
    private val historyRepository = HistoryRepository(
        RetrofitClient.instance,
        AppDatabase.getInstance(application).historyDao(),
        AppDatabase.getInstance(application).hintDao(),
        application
    )

    // Quick access to SharedPreferences for UI state (like sort order)
    private val uiPrefs by lazy {
        application.getSharedPreferences("ap_tracker_ui_prefs", Context.MODE_PRIVATE)
    }

    // --- User Profile State ---
    private val _userProfile = MutableStateFlow<UserProfile?>(null)
    val userProfile = _userProfile.asStateFlow()

    // --- Persistent Slots View Preferences ---
    val slotsShowFinished: StateFlow<Boolean> = settingsManager.slotsShowFinished
        .stateIn(viewModelScope, SharingStarted.Lazily, false)

    val expandedRoomIds: StateFlow<Set<Int>> = settingsManager.expandedRoomIds
        .stateIn(viewModelScope, SharingStarted.Lazily, emptySet())

    fun setSlotsShowFinished(show: Boolean) {
        viewModelScope.launch {
            settingsManager.setSlotsShowFinished(show)
        }
    }

    fun setRoomExpanded(roomDbId: Int, isExpanded: Boolean) {
        viewModelScope.launch {
            val current = expandedRoomIds.value.toMutableSet()
            if (isExpanded) {
                current.add(roomDbId)
            } else {
                current.remove(roomDbId)
            }
            settingsManager.setExpandedRoomIds(current)
        }
    }

    fun setAllRoomsExpanded(roomDbIds: List<Int>, expand: Boolean) {
        viewModelScope.launch {
            val next = if (expand) roomDbIds.toSet() else emptySet()
            settingsManager.setExpandedRoomIds(next)
        }
    }

    private val _trackedSlotsByRoom = MutableStateFlow<List<RoomWithTrackedSlots>>(emptyList())
    val trackedSlotsByRoom = _trackedSlotsByRoom.asStateFlow()

    private val _thresholdGroups = MutableStateFlow<List<ThresholdGroup>>(emptyList())
    val thresholdGroups = _thresholdGroups.asStateFlow()
    private var latestThresholdGroupsKey: Pair<Int, Int>? = null

    private val _milestoneTemplates = MutableStateFlow<List<MilestoneTemplate>>(emptyList())
    val milestoneTemplates = _milestoneTemplates.asStateFlow()
    private var milestoneTemplatesRequestId = 0
    private var latestMilestoneTemplatesGame: String? = null

    private val _availableItems = MutableStateFlow<List<AutocompleteOption>>(emptyList())
    val availableItems = _availableItems.asStateFlow()

    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    private val _integrationMessage = MutableStateFlow<String?>(null)
    val integrationMessage = _integrationMessage.asStateFlow()

    val isAutoSyncEnabled = settingsManager.isAutoSyncEnabled.stateIn(
        viewModelScope,
        SharingStarted.Eagerly,
        true
    )

    val dateFormatPreset = settingsManager.dateFormatPreset.stateIn(
        viewModelScope,
        SharingStarted.Eagerly,
        "SYSTEM_DEFAULT"
    )

    // --- Ignore List & Sorting State ---
    private val _ignoreList = MutableStateFlow<List<IgnoreItem>>(emptyList())
    val ignoreList = _ignoreList.asStateFlow()

    private val _knownGames = MutableStateFlow<List<String>>(emptyList())
    val knownGames = _knownGames.asStateFlow()

    private val _gameAvailableItems = MutableStateFlow<List<AutocompleteOption>>(emptyList())
    val gameAvailableItems = _gameAvailableItems.asStateFlow()

    private var fetchAvailableItemsJob: kotlinx.coroutines.Job? = null
    private var latestGameQuery: String? = null

    private val _ignoreSortOption = MutableStateFlow(IgnoreSortOption.NEWEST)
    val ignoreSortOption = _ignoreSortOption.asStateFlow()

    // --- Whitelist & Sorting State ---
    private val _whitelist = MutableStateFlow<List<WhitelistItem>>(emptyList())
    val whitelist = _whitelist.asStateFlow()

    private val _whitelistSortOption = MutableStateFlow(IgnoreSortOption.NEWEST)
    val whitelistSortOption = _whitelistSortOption.asStateFlow()

    init {
        fetchUserProfile()
        fetchTrackedSlots()
        fetchIgnoreList()
        fetchWhitelist()
        loadSortPreference()
    }

    // ============================================================================================
    // PREFERENCES & SORTING
    // ============================================================================================

    fun setAutoSync(isEnabled: Boolean) {
        viewModelScope.launch {
            settingsManager.setAutoSync(isEnabled)
        }
    }

    fun setDateFormatPreset(preset: String) {
        viewModelScope.launch {
            settingsManager.setDateFormatPreset(preset)
        }
    }

    fun setIgnoreSortOption(option: IgnoreSortOption) {
        _ignoreSortOption.value = option
        saveSortPreference(option)
    }

    private fun loadSortPreference() {
        val savedName = uiPrefs.getString("IGNORE_SORT_ORDER", IgnoreSortOption.NEWEST.name)
        _ignoreSortOption.value = try {
            IgnoreSortOption.valueOf(savedName ?: IgnoreSortOption.NEWEST.name)
        } catch (e: Exception) {
            IgnoreSortOption.NEWEST
        }
    }

    private fun saveSortPreference(option: IgnoreSortOption) {
        uiPrefs.edit().putString("IGNORE_SORT_ORDER", option.name).apply()
    }

    // ============================================================================================
    // API OPERATIONS: USER & SLOTS
    // ============================================================================================

    fun fetchUserProfile() {
        viewModelScope.launch {
            try {
                val profile = RetrofitClient.instance.getUserProfile()
                _userProfile.value = profile
                settingsManager.setCheeseConnected(profile.is_cheese_connected)
            } catch (e: Exception) {
                _errorMessage.value = "Failed to load user profile."
                e.printStackTrace()
            }
        }
    }

    fun fetchTrackedSlots() {
        viewModelScope.launch { loadTrackedSlots() }
    }

    /** Awaitable tracked-slots load, so callers (e.g. refresh) can sequence work. */
    private suspend fun loadTrackedSlots() {
        try {
            _trackedSlotsByRoom.value = RetrofitClient.instance.getUserTrackedSlots()
        } catch (e: Exception) {
            _errorMessage.value = "Failed to load tracked slots."
            e.printStackTrace()
            _trackedSlotsByRoom.value = emptyList()
        }
    }

    fun updateGlobalPreferences(
        progression: Boolean? = null,
        useful: Boolean? = null,
        hints: Boolean? = null,
        remoteHints: Boolean? = null,
        filler: Boolean? = null,
        trap: Boolean? = null,
        uiShowFiller: Boolean? = null,
        uiShowTrap: Boolean? = null,
        finished: Boolean? = null,
        useCondensed: Boolean? = null,
        suppressOwn: Boolean? = null,
        combine: Boolean? = null,
        removeEmojis: Boolean? = null,
        suppressSelfFound: Boolean? = null,
        suppressConnected: Boolean? = null
    ) {
        viewModelScope.launch {
            try {
                // Using a Map allows us to send only the fields that changed.
                val params = mutableMapOf<String, Boolean>()

                progression?.let { params["notify_progression"] = it }
                useful?.let { params["notify_useful"] = it }
                filler?.let { params["notify_filler"] = it }
                trap?.let { params["notify_trap"] = it }
                uiShowFiller?.let { params["ui_show_filler"] = it }
                uiShowTrap?.let { params["ui_show_trap"] = it }
                hints?.let { params["notify_hints"] = it }
                remoteHints?.let { params["notify_hints_remote_items"] = it }
                finished?.let { params["notify_finished"] = it }
                useCondensed?.let { params["use_condensed_messages"] = it }
                suppressOwn?.let { params["suppress_own_events"] = it }
                combine?.let { params["combine_notifications"] = it }
                removeEmojis?.let { params["remove_emojis"] = it }
                suppressSelfFound?.let { params["suppress_self_found"] = it }
                suppressConnected?.let { params["suppress_connected"] = it }

                if (params.isNotEmpty()) {
                    RetrofitClient.instance.updateUserPreferences(params)
                }

                fetchUserProfile()

            } catch (e: Exception) {
                _errorMessage.value = "Failed to save preferences."
                e.printStackTrace()
            }
        }
    }

    fun updateSlotPreferences(roomId: Int, slotId: Int, key: String, value: Boolean?) {
        viewModelScope.launch {
            val previousRooms = _trackedSlotsByRoom.value
            try {
                // 1. Find the current state of the slot from your local list
                val currentRoom = previousRooms.find { it.room_db_id == roomId }
                val currentSlot = currentRoom?.tracked_slots?.find { it.slot_id == slotId }

                if (currentSlot == null) {
                    return@launch
                }

                // 2. Create the updated slot object optimistically
                val updatedSlot = when (key) {
                    "notify_progression" -> currentSlot.copy(notify_progression = value)
                    "notify_useful" -> currentSlot.copy(notify_useful = value)
                    "notify_filler" -> currentSlot.copy(notify_filler = value)
                    "notify_trap" -> currentSlot.copy(notify_trap = value)
                    "notify_hints" -> currentSlot.copy(notify_hints = value)
                    "notify_hints_remote_items" -> currentSlot.copy(notify_hints_remote_items = value)
                    "notify_finished" -> currentSlot.copy(notify_finished = value)
                    "combine_notifications" -> currentSlot.copy(combine_notifications = value)
                    "suppress_own_events" -> currentSlot.copy(suppress_own_events = value)
                    "remove_emojis" -> currentSlot.copy(remove_emojis = value)
                    "suppress_self_found" -> currentSlot.copy(suppress_self_found = value)
                    "use_condensed_messages" -> currentSlot.copy(use_condensed_messages = value)
                    "suppress_connected" -> currentSlot.copy(suppress_connected = value)
                    else -> currentSlot
                }

                // 3. Optimistically update local UI state immediately
                val updatedRooms = previousRooms.map { room ->
                    if (room.room_db_id == roomId) {
                        room.copy(
                            tracked_slots = room.tracked_slots.map { slot ->
                                if (slot.slot_id == slotId) updatedSlot else slot
                            }
                        )
                    } else {
                        room
                    }
                }
                _trackedSlotsByRoom.value = updatedRooms

                // 4. Construct request payload and send to backend
                val request = UpdateSlotPrefsRequest(
                    notify_progression = updatedSlot.notify_progression,
                    notify_useful = updatedSlot.notify_useful,
                    notify_filler = updatedSlot.notify_filler,
                    notify_trap = updatedSlot.notify_trap,
                    notify_hints = updatedSlot.notify_hints,
                    notify_hints_remote_items = updatedSlot.notify_hints_remote_items,
                    notify_finished = updatedSlot.notify_finished,
                    combine_notifications = updatedSlot.combine_notifications,
                    suppress_own_events = updatedSlot.suppress_own_events,
                    remove_emojis = updatedSlot.remove_emojis,
                    suppress_self_found = updatedSlot.suppress_self_found,
                    use_condensed_messages = updatedSlot.use_condensed_messages,
                    suppress_connected = updatedSlot.suppress_connected
                )

                val response = RetrofitClient.instance.updateSlotPreferences(roomId, slotId, request)

                if (!response.isSuccessful) {
                    _trackedSlotsByRoom.value = previousRooms
                    _errorMessage.value = "Failed to update settings: ${response.code()}"
                }
            } catch (e: Exception) {
                _trackedSlotsByRoom.value = previousRooms
                _errorMessage.value = "Failed to save slot settings."
                e.printStackTrace()
            }
        }
    }

    fun deleteAccount(onAccountDeleted: () -> Unit) {
        viewModelScope.launch {
            _errorMessage.value = null
            try {
                RetrofitClient.instance.deleteAccount()
                onAccountDeleted()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to delete account. Please try again."
                e.printStackTrace()
            }
        }
    }

    fun clearErrorMessage() {
        _errorMessage.value = null
    }

    // ============================================================================================
    // CHEESE TRACKER INTEGRATION
    // ============================================================================================

    fun connectCheeseTracker(apiKey: String) {
        viewModelScope.launch {
            try {
                val request = CheeseAuthRequest(apiKey)
                val response = RetrofitClient.instance.connectCheeseTracker(request)

                _integrationMessage.value = response.message
                fetchUserProfile()
                fetchTrackedSlots()
            } catch (e: Exception) {
                e.printStackTrace()
                _errorMessage.value = "Failed to connect. Check your key."
            }
        }
    }

    fun manualSyncCheese() {
        viewModelScope.launch {
            try {
                val response = RetrofitClient.instance.syncCheeseTracker()
                _integrationMessage.value = response.message
                fetchTrackedSlots()
            } catch (e: Exception) {
                e.printStackTrace()
                _errorMessage.value = "Sync failed. Are you connected?"
            }
        }
    }

    fun disconnectCheese() {
        viewModelScope.launch {
            try {
                RetrofitClient.instance.disconnectCheeseTracker()
                _integrationMessage.value = "Disconnected from Cheese Tracker."
                settingsManager.setCheeseConnected(false)
                fetchUserProfile()
            } catch (e: Exception) {
                e.printStackTrace()
                _errorMessage.value = "Failed to disconnect."
            }
        }
    }

    fun clearIntegrationMessage() {
        _integrationMessage.value = null
    }

    // --- Cheese slot state (notes / status / ping) editing ---

    /** True while a Cheese slot write is in flight, to disable controls. */
    private val _isSavingCheeseSlot = MutableStateFlow(false)
    val isSavingCheeseSlot: StateFlow<Boolean> = _isSavingCheeseSlot.asStateFlow()

    /** True while an on-demand Cheese Tracker refresh is in flight. */
    private val _isRefreshingCheese = MutableStateFlow(false)
    val isRefreshingCheese: StateFlow<Boolean> = _isRefreshingCheese.asStateFlow()

    /**
     * Applies an optimistic change to a slot's Cheese state, sends the partial
     * update to the backend, then reconciles the local state against the
     * server's authoritative response (Cheese may force-upgrade completion).
     * Rolls back and surfaces an error on failure.
     */
    private fun submitCheeseSlotUpdate(
        roomId: Int,
        slotId: Int,
        updates: Map<String, Any>,
        optimistic: (CheeseSlotState) -> CheeseSlotState
    ) {
        viewModelScope.launch {
            val previousRooms = _trackedSlotsByRoom.value
            val currentRoom = previousRooms.find { it.room_db_id == roomId }
            val currentSlot = currentRoom?.tracked_slots?.find { it.slot_id == slotId }
            val currentCheese = currentSlot?.cheese ?: return@launch

            // 1. Optimistic local update.
            _trackedSlotsByRoom.value = replaceSlotCheese(previousRooms, roomId, slotId, optimistic(currentCheese))
            _isSavingCheeseSlot.value = true

            try {
                val response = RetrofitClient.instance.updateSlotCheese(roomId, slotId, updates)
                val body = response.body()
                if (response.isSuccessful && body?.cheese != null) {
                    // 2. Reconcile with the authoritative server state.
                    _trackedSlotsByRoom.value = replaceSlotCheese(
                        _trackedSlotsByRoom.value, roomId, slotId, body.cheese
                    )
                } else {
                    _trackedSlotsByRoom.value = previousRooms
                    _errorMessage.value = when (response.code()) {
                        403 -> "This slot is claimed by someone else on Cheese Tracker."
                        409 -> "This slot changed on Cheese Tracker. Pull to refresh and try again."
                        429 -> "Too many updates. Please slow down."
                        502 -> "Could not reach Cheese Tracker. Please try again."
                        else -> "Failed to update Cheese Tracker."
                    }
                }
            } catch (e: Exception) {
                _trackedSlotsByRoom.value = previousRooms
                _errorMessage.value = "Failed to update Cheese Tracker."
                e.printStackTrace()
            } finally {
                _isSavingCheeseSlot.value = false
            }
        }
    }

    private fun replaceSlotCheese(
        rooms: List<RoomWithTrackedSlots>,
        roomId: Int,
        slotId: Int,
        newCheese: CheeseSlotState
    ): List<RoomWithTrackedSlots> {
        return rooms.map { room ->
            if (room.room_db_id == roomId) {
                room.copy(
                    tracked_slots = room.tracked_slots.map { slot ->
                        if (slot.slot_id == slotId) slot.copy(cheese = newCheese) else slot
                    }
                )
            } else {
                room
            }
        }
    }

    fun updateCheeseNotes(roomId: Int, slotId: Int, notes: String) {
        submitCheeseSlotUpdate(roomId, slotId, mapOf("notes" to notes)) { it.copy(notes = notes) }
    }

    fun updateCheeseProgression(roomId: Int, slotId: Int, status: String) {
        submitCheeseSlotUpdate(
            roomId, slotId, mapOf("progression_status" to status)
        ) { it.copy(progression_status = status) }
    }

    fun updateCheeseCompletion(roomId: Int, slotId: Int, status: String) {
        submitCheeseSlotUpdate(
            roomId, slotId, mapOf("completion_status" to status)
        ) { it.copy(completion_status = status) }
    }

    fun updateCheesePing(roomId: Int, slotId: Int, ping: String) {
        submitCheeseSlotUpdate(
            roomId, slotId, mapOf("discord_ping" to ping)
        ) { it.copy(discord_ping = ping) }
    }

    /** "Still BK": refresh last_checked without changing status. */
    fun stillBk(roomId: Int, slotId: Int) {
        submitCheeseSlotUpdate(roomId, slotId, mapOf("touch_last_checked" to true)) { it }
    }

    /**
     * Forces the backend to pull this room's current state from Cheese Tracker
     * (bypassing the ~5 min poll), then reloads tracked slots so the UI shows it.
     */
    fun refreshCheeseFromServer(roomId: Int, onComplete: () -> Unit = {}) {
        viewModelScope.launch {
            _isRefreshingCheese.value = true
            try {
                val response = RetrofitClient.instance.refreshRoomCheese(roomId)
                if (response.isSuccessful) {
                    loadTrackedSlots()
                } else {
                    _errorMessage.value = when (response.code()) {
                        429 -> "Refreshing too fast. Please wait a moment."
                        502 -> "Could not reach Cheese Tracker. Please try again."
                        else -> "Failed to refresh from Cheese Tracker."
                    }
                }
            } catch (e: Exception) {
                _errorMessage.value = "Failed to refresh from Cheese Tracker."
                e.printStackTrace()
            } finally {
                _isRefreshingCheese.value = false
                onComplete()
            }
        }
    }

    /** Sets (or clears, when null) the user's default Cheese ping preference. */
    fun updateCheeseDefaultPing(ping: String?) {
        viewModelScope.launch {
            val previousProfile = _userProfile.value
            _userProfile.value = previousProfile?.copy(cheese_default_ping = ping)
            try {
                val response = RetrofitClient.instance.updateCheeseDefaultPing(
                    UpdateCheesePingRequest(ping)
                )
                if (!response.isSuccessful) {
                    _userProfile.value = previousProfile
                    _errorMessage.value = "Failed to save default ping."
                }
            } catch (e: Exception) {
                _userProfile.value = previousProfile
                _errorMessage.value = "Failed to save default ping."
                e.printStackTrace()
            }
        }
    }

    // ============================================================================================
    // IGNORE LIST LOGIC
    // ============================================================================================

    fun fetchIgnoreList() {
        viewModelScope.launch {
            try {
                _ignoreList.value = userRepository.getIgnoreList()
            } catch (e: java.net.UnknownHostException) {
                Log.e("UserViewModel", "Network error: Could not resolve host. Check your DEV_API_BASE_URL in local.properties.", e)
                _errorMessage.value = "Network error: Cannot reach server. (Host unreachable)"
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to fetch ignore list", e)
                _errorMessage.value = "Failed to load ignore list. Check connection."
            }
        }
    }

    fun fetchKnownGames() {
        viewModelScope.launch {
            try {
                val games = RetrofitClient.instance.getKnownGames()
                _knownGames.value = games
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to fetch games list", e)
                _errorMessage.value = "Could not load game list."
            }
        }
    }

    fun fetchGameAvailableItems(gameName: String) {
        latestGameQuery = gameName
        fetchAvailableItemsJob?.cancel()
        fetchAvailableItemsJob = viewModelScope.launch {
            // 1. Instantly load local Room DB cache if available (0ms wait time)
            val localCache = try {
                val db = AppDatabase.getInstance(getApplication())
                db.datapackageDao().getDatapackageForGame(gameName)
            } catch (e: Exception) {
                null
            }

            if (localCache != null && latestGameQuery == gameName) {
                try {
                    val type = object : TypeToken<List<AutocompleteOption>>() {}.type
                    val cachedItems: List<AutocompleteOption> = Gson().fromJson(localCache.itemsJson, type)
                    if (cachedItems.isNotEmpty()) {
                        _gameAvailableItems.value = cachedItems
                    }
                } catch (e: Exception) {
                    Log.e("UserViewModel", "Failed to parse local datapackage cache", e)
                }
            }

            // 2. Revalidate from API in background and update local Room DB cache
            try {
                val items = RetrofitClient.instance.getGameAvailableItems(gameName)
                if (latestGameQuery == gameName) {
                    _gameAvailableItems.value = items
                    val gson = Gson()
                    val itemsJson = gson.toJson(items)
                    val db = AppDatabase.getInstance(getApplication())
                    val existing = db.datapackageDao().getDatapackageForGame(gameName)
                    val updated = CachedDatapackageEntity(
                        cacheKey = "game:$gameName",
                        game = gameName,
                        itemsJson = itemsJson,
                        locationsJson = existing?.locationsJson ?: "[]",
                        updatedAt = System.currentTimeMillis()
                    )
                    db.datapackageDao().insertDatapackage(updated)
                }
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to fetch game available items from remote API", e)
            }
        }
    }

    fun clearGameAvailableItems() {
        latestGameQuery = null
        fetchAvailableItemsJob?.cancel()
        _gameAvailableItems.value = emptyList()
    }

    fun addIgnoreItem(itemName: String, gameName: String?, isGroup: Boolean = false) {
        viewModelScope.launch {
            try {
                userRepository.addIgnoreItem(itemName, gameName, isGroup)
                fetchIgnoreList()
                _integrationMessage.value = "Item ignored."
            } catch (e: HttpException) {
                if (e.code() == 409) {
                    _errorMessage.value = "'$itemName' is already on your ignore list."
                } else {
                    Log.e("UserViewModel", "Failed to add ignore rule (HTTP ${e.code()})", e)
                    _errorMessage.value = "Failed to add ignore rule (HTTP ${e.code()})."
                }
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to add ignore rule", e)
                _errorMessage.value = "Failed to add ignore rule. Check connection."
            }
        }
    }

    fun updateIgnoreItem(id: Int, itemName: String, gameName: String?, isGroup: Boolean = false) {
        viewModelScope.launch {
            try {
                val request = com.jones.aptracker.network.AddIgnoreItemRequest(itemName, gameName, isGroup)
                val response = RetrofitClient.instance.updateIgnoreItem(id, request)

                if (response.isSuccessful) {
                    fetchIgnoreList()
                    _integrationMessage.value = "Rule updated."
                } else {
                    if (response.code() == 409) {
                        _errorMessage.value = "A rule for '$itemName' already exists."
                    } else {
                        _errorMessage.value = "Failed to update rule."
                    }
                }
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to update rule", e)
                _errorMessage.value = "Failed to update rule. Check connection."
            }
        }
    }

    fun deleteIgnoreItem(itemId: Int) {
        viewModelScope.launch {
            try {
                // Optimistic UI update
                val currentList = _ignoreList.value
                _ignoreList.value = currentList.filter { it.id != itemId }

                userRepository.deleteIgnoreItem(itemId)
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to remove rule", e)
                _errorMessage.value = "Failed to remove rule."
                fetchIgnoreList() // Revert UI on failure
            }
        }
    }

    fun setWhitelistSortOption(option: IgnoreSortOption) {
        _whitelistSortOption.value = option
    }

    fun fetchWhitelist() {
        viewModelScope.launch {
            try {
                _whitelist.value = userRepository.getWhitelist()
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to fetch whitelist", e)
                _errorMessage.value = "Failed to load whitelist. Check connection."
            }
        }
    }

    fun addWhitelistItem(itemName: String, gameName: String?, isGroup: Boolean = false) {
        viewModelScope.launch {
            try {
                userRepository.addWhitelistItem(itemName, gameName, isGroup)
                fetchWhitelist()
                _integrationMessage.value = "Item whitelisted."
            } catch (e: retrofit2.HttpException) {
                if (e.code() == 409) {
                    _errorMessage.value = "'$itemName' is already on your whitelist."
                } else {
                    Log.e("UserViewModel", "Failed to add whitelist rule (HTTP ${e.code()})", e)
                    _errorMessage.value = "Failed to add whitelist rule (HTTP ${e.code()})."
                }
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to add whitelist rule", e)
                _errorMessage.value = "Failed to add whitelist rule. Check connection."
            }
        }
    }

    fun updateWhitelistItem(id: Int, itemName: String, gameName: String?, isGroup: Boolean = false) {
        viewModelScope.launch {
            try {
                userRepository.updateWhitelistItem(id, itemName, gameName, isGroup)
                fetchWhitelist()
                _integrationMessage.value = "Rule updated."
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to update rule", e)
                _errorMessage.value = "Failed to update rule. Check connection."
            }
        }
    }

    fun deleteWhitelistItem(itemId: Int) {
        viewModelScope.launch {
            try {
                // Optimistic UI update
                val currentList = _whitelist.value
                _whitelist.value = currentList.filter { it.id != itemId }

                userRepository.deleteWhitelistItem(itemId)
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to remove whitelist rule", e)
                _errorMessage.value = "Failed to remove rule."
                fetchWhitelist() // Revert UI on failure
            }
        }
    }

    // ============================================================================================
    // SNOOZE LOGIC
    // ============================================================================================

    fun setGlobalSnooze(durationMinutes: Int) {
        // 1. CALCULATE LOCALLY (Optimistic)
        val optimisticTime = if (durationMinutes > 0) {
            Instant.now().plus(durationMinutes.toLong(), ChronoUnit.MINUTES).toString()
        } else {
            null
        }

        // 2. SAVE OLD STATE (In case we need to revert)
        val oldProfile = _userProfile.value

        // 3. UPDATE UI IMMEDIATELY
        _userProfile.value = oldProfile?.copy(global_snooze_until = optimisticTime)

        val status = if (durationMinutes > 0) "App snoozed." else "App active."
        _integrationMessage.value = status

        viewModelScope.launch {
            try {
                // 4. NETWORK CALL (Happens in background)
                val request = SnoozeRequest(durationMinutes)
                val response = RetrofitClient.instance.setGlobalSnooze(request)

                // 5. CONFIRMATION (Update with authoritative server time)
                _userProfile.value = _userProfile.value?.copy(
                    global_snooze_until = response.snooze_until
                )
            } catch (e: Exception) {
                e.printStackTrace()
                // 6. REVERT ON FAILURE
                _userProfile.value = oldProfile
                _errorMessage.value = "Failed to set snooze. Check connection."
            }
        }
    }

    fun setSlotSnooze(roomId: Int, slotId: Int, durationMinutes: Int) {
        // 1. CALCULATE LOCALLY
        val optimisticTime = if (durationMinutes > 0) {
            Instant.now().plus(durationMinutes.toLong(), ChronoUnit.MINUTES).toString()
        } else {
            null
        }

        // 2. SAVE OLD STATE
        val oldRooms = _trackedSlotsByRoom.value

        // 3. UPDATE UI IMMEDIATELY (Complex List Mapping)
        val optimisticRooms = oldRooms.map { room ->
            if (room.room_db_id == roomId) {
                val updatedSlots = room.tracked_slots.map { slot ->
                    if (slot.slot_id == slotId) {
                        slot.copy(snooze_until = optimisticTime)
                    } else {
                        slot
                    }
                }
                room.copy(tracked_slots = updatedSlots)
            } else {
                room
            }
        }
        _trackedSlotsByRoom.value = optimisticRooms

        val status = if (durationMinutes > 0) "Player snoozed." else "Player active."
        _integrationMessage.value = status

        viewModelScope.launch {
            try {
                // 4. NETWORK CALL
                val request = SnoozeRequest(durationMinutes)
                // We don't strictly need to parse the response here because we already updated the UI,
                // but doing so ensures our local clock matches the server clock eventually.
                val response = RetrofitClient.instance.setSlotSnooze(roomId, slotId, request)

            } catch (e: Exception) {
                e.printStackTrace()
                // 5. REVERT ON FAILURE
                _trackedSlotsByRoom.value = oldRooms
                _errorMessage.value = "Failed to snooze player."
            }
        }
    }

    fun wakeUpEverything() {
        viewModelScope.launch {
            // 1. Clear Global Snooze
            setGlobalSnooze(0)

            // 2. Find all currently snoozed slots
            val currentRooms = _trackedSlotsByRoom.value
            val snoozedSlots = currentRooms.flatMap { room ->
                room.tracked_slots.map { slot -> room.room_db_id to slot }
            }.filter { (_, slot) ->
                slot.snooze_until != null
            }

            if (snoozedSlots.isNotEmpty()) {
                Log.d("UserViewModel", "Waking up ${snoozedSlots.size} slots...")

                // 3. Clear each slot (Launching parallel jobs for speed)
                snoozedSlots.forEach { (roomId, slot) ->
                    launch {
                        // reuse existing setSlotSnooze logic but send 0
                        setSlotSnooze(roomId, slot.slot_id, 0)
                    }
                }
                _integrationMessage.value = "All snoozes cleared."
            }
        }
    }

    fun clearLocalHistory() {
        viewModelScope.launch {
            try {
                historyRepository.clearAllHistory()
                _integrationMessage.value = "Local history cleared."
            } catch (e: Exception) {
                _errorMessage.value = "Failed to clear local history."
                e.printStackTrace()
            }
        }
    }

    fun sendTestNotification() {
        viewModelScope.launch {
            try {
                val response = RetrofitClient.instance.sendTestNotification()
                if (response.isSuccessful) {
                    _integrationMessage.value = "Test Notification Sent!"
                } else {
                    _errorMessage.value = "Failed to trigger test: ${response.code()}"
                }
            } catch (e: Exception) {
                e.printStackTrace()
                _errorMessage.value = "Connection failed."
            }
        }
    }

    fun applySlotSettingsToAll(roomId: Int, sourceSlotId: Int) {
        viewModelScope.launch {
            try {
                // 1. Get source data
                val room = _trackedSlotsByRoom.value.find { it.room_db_id == roomId } ?: return@launch
                val sourceSlot = room.tracked_slots.find { it.slot_id == sourceSlotId } ?: return@launch

                // 2. Loop through targets
                room.tracked_slots.forEach { targetSlot ->
                    if (targetSlot.slot_id != sourceSlotId) {
                        // Create request with SOURCE values
                        val request = UpdateSlotPrefsRequest(
                            notify_progression = sourceSlot.notify_progression,
                            notify_useful = sourceSlot.notify_useful,
                            notify_filler = sourceSlot.notify_filler,
                            notify_trap = sourceSlot.notify_trap,
                            notify_hints = sourceSlot.notify_hints,
                            notify_hints_remote_items = sourceSlot.notify_hints_remote_items,
                            notify_finished = sourceSlot.notify_finished,
                            combine_notifications = sourceSlot.combine_notifications,
                            suppress_own_events = sourceSlot.suppress_own_events,
                            remove_emojis = sourceSlot.remove_emojis,
                            suppress_self_found = sourceSlot.suppress_self_found,
                            use_condensed_messages = sourceSlot.use_condensed_messages
                        )
                        RetrofitClient.instance.updateSlotPreferences(roomId, targetSlot.slot_id, request)
                    }
                }

                fetchTrackedSlots() // Refresh UI
                _integrationMessage.value = "Settings applied to all slots."

            } catch (e: Exception) {
                _errorMessage.value = "Failed to apply settings."
                e.printStackTrace()
            }
        }
    }

    // ============================================================================================
    // THRESHOLDS
    // ============================================================================================

    fun fetchThresholdGroups(roomDbId: Int, slotId: Int) {
        val requestKey = roomDbId to slotId
        if (latestThresholdGroupsKey != requestKey) {
            _thresholdGroups.value = emptyList()
        }
        latestThresholdGroupsKey = requestKey
        viewModelScope.launch {
            try {
                val groups = RetrofitClient.instance.getThresholdGroups(roomDbId, slotId)
                if (latestThresholdGroupsKey == requestKey) {
                    _thresholdGroups.value = groups
                }
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to fetch threshold groups", e)
            }
        }
    }

    fun createThresholdGroup(
        roomDbId: Int,
        slotId: Int,
        name: String?,
        items: List<ThresholdGroupItemRequest>
    ) {
        viewModelScope.launch {
            try {
                val request = CreateThresholdGroupRequest(name, items)
                val response = RetrofitClient.instance.createThresholdGroup(roomDbId, slotId, request)
                if (response.isSuccessful) {
                    fetchThresholdGroups(roomDbId, slotId)
                    _integrationMessage.value = "Milestone group created."
                } else {
                    _errorMessage.value = "Failed to create milestone group: ${response.code()}"
                }
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to create threshold group", e)
                _errorMessage.value = "Failed to create milestone group. Check connection."
            }
        }
    }

    fun updateThresholdGroup(
        roomDbId: Int,
        slotId: Int,
        groupId: Int,
        name: String?,
        items: List<ThresholdGroupItemRequest>
    ) {
        viewModelScope.launch {
            try {
                val request = CreateThresholdGroupRequest(name, items)
                val response = RetrofitClient.instance.updateThresholdGroup(roomDbId, slotId, groupId, request)
                if (response.isSuccessful) {
                    fetchThresholdGroups(roomDbId, slotId)
                    _integrationMessage.value = "Milestone group updated."
                } else {
                    _errorMessage.value = "Failed to update milestone group: ${response.code()}"
                }
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to update threshold group", e)
                _errorMessage.value = "Failed to update milestone group. Check connection."
            }
        }
    }

    fun deleteThresholdGroup(roomDbId: Int, slotId: Int, groupId: Int) {
        viewModelScope.launch {
            try {
                val response = RetrofitClient.instance.deleteThresholdGroup(roomDbId, slotId, groupId)
                if (response.isSuccessful) {
                    fetchThresholdGroups(roomDbId, slotId)
                } else {
                    _errorMessage.value = "Failed to delete milestone group: ${response.code()}"
                }
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to delete threshold group", e)
                _errorMessage.value = "Failed to delete milestone group. Check connection."
            }
        }
    }

    // ============================================================================================
    // MILESTONE TEMPLATES
    // ============================================================================================

    fun fetchMilestoneTemplates(game: String? = null) {
        val requestId = ++milestoneTemplatesRequestId
        latestMilestoneTemplatesGame = game
        viewModelScope.launch {
            try {
                val templates = RetrofitClient.instance.getMilestoneTemplates(game)
                if (requestId == milestoneTemplatesRequestId) {
                    _milestoneTemplates.value = templates
                }
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to fetch milestone templates", e)
            }
        }
    }

    fun createMilestoneTemplate(
        name: String,
        gameName: String,
        items: List<ThresholdGroupItemRequest>,
        onConflict: (() -> Unit)? = null,
        onSuccess: (() -> Unit)? = null
    ) {
        viewModelScope.launch {
            try {
                val request = CreateMilestoneTemplateRequest(name, gameName, items)
                val response = RetrofitClient.instance.createMilestoneTemplate(request)
                if (response.isSuccessful) {
                    fetchMilestoneTemplates(latestMilestoneTemplatesGame)
                    _integrationMessage.value = "Template saved."
                    onSuccess?.invoke()
                } else if (response.code() == 409) {
                    if (onConflict != null) {
                        onConflict()
                    } else {
                        _errorMessage.value = "A template named '$name' already exists for $gameName."
                    }
                } else {
                    _errorMessage.value = "Failed to save template: ${response.code()}"
                }
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to create milestone template", e)
                _errorMessage.value = "Failed to save template. Check connection."
            }
        }
    }

    fun updateMilestoneTemplate(
        templateId: Int,
        name: String,
        gameName: String,
        items: List<ThresholdGroupItemRequest>,
        onSuccess: (() -> Unit)? = null
    ) {
        viewModelScope.launch {
            try {
                val request = CreateMilestoneTemplateRequest(name, gameName, items)
                val response = RetrofitClient.instance.updateMilestoneTemplate(templateId, request)
                if (response.isSuccessful) {
                    fetchMilestoneTemplates(latestMilestoneTemplatesGame)
                    _integrationMessage.value = "Template updated."
                    onSuccess?.invoke()
                } else {
                    _errorMessage.value = "Failed to update template: ${response.code()}"
                }
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to update milestone template", e)
                _errorMessage.value = "Failed to update template. Check connection."
            }
        }
    }

    fun deleteMilestoneTemplate(templateId: Int) {
        viewModelScope.launch {
            val currentList = _milestoneTemplates.value
            _milestoneTemplates.value = currentList.filter { it.id != templateId }
            try {
                val response = RetrofitClient.instance.deleteMilestoneTemplate(templateId)
                if (!response.isSuccessful) {
                    _errorMessage.value = "Failed to delete template: ${response.code()}"
                    _milestoneTemplates.value = currentList
                }
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to delete milestone template", e)
                _errorMessage.value = "Failed to delete template. Check connection."
                _milestoneTemplates.value = currentList
            }
        }
    }

    fun fetchAvailableItems(roomDbId: Int, slotId: Int) {
        viewModelScope.launch {
            val room = trackedSlotsByRoom.value.find { it.room_db_id == roomDbId }
            val slot = room?.tracked_slots?.find { it.slot_id == slotId }
            val gameName = slot?.game
            val key = if (!gameName.isNullOrEmpty()) "game:$gameName" else "slot:$roomDbId:$slotId"

            val localCache = try {
                val db = AppDatabase.getInstance(getApplication())
                db.datapackageDao().getDatapackage(key, roomDbId, slotId, gameName)
            } catch (e: Exception) { null }

            if (localCache != null) {
                try {
                    val type = object : TypeToken<List<AutocompleteOption>>() {}.type
                    val cachedItems: List<AutocompleteOption> = Gson().fromJson(localCache.itemsJson, type)
                    if (cachedItems.isNotEmpty()) {
                        _availableItems.value = cachedItems
                    }
                } catch (e: Exception) {
                    Log.e("UserViewModel", "Failed to parse local datapackage items", e)
                }
            }

            try {
                val items = RetrofitClient.instance.getAvailableItems(roomDbId, slotId)
                _availableItems.value = items
                
                val gson = Gson()
                val itemsJson = gson.toJson(items)
                val db = AppDatabase.getInstance(getApplication())

                db.datapackageDao().insertDatapackage(
                    CachedDatapackageEntity(
                        cacheKey = "slot:$roomDbId:$slotId",
                        game = gameName,
                        roomDbId = roomDbId,
                        slotId = slotId,
                        itemsJson = itemsJson,
                        locationsJson = localCache?.locationsJson ?: "[]",
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
                            locationsJson = localCache?.locationsJson ?: "[]",
                            updatedAt = System.currentTimeMillis()
                        )
                    )
                }
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to fetch available items", e)
            }
        }
    }
}