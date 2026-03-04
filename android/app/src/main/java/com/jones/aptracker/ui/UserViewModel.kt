package com.jones.aptracker.ui

import android.app.Application
import android.content.Context
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.data.SettingsManager
import com.jones.aptracker.network.CheeseAuthRequest
import com.jones.aptracker.network.IgnoreItem
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.RoomWithTrackedSlots
import com.jones.aptracker.network.UpdateSlotPrefsRequest
import com.jones.aptracker.network.UserProfile
import com.jones.aptracker.network.SnoozeRequest
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

    // Quick access to SharedPreferences for UI state (like sort order)
    private val uiPrefs by lazy {
        application.getSharedPreferences("ap_tracker_ui_prefs", Context.MODE_PRIVATE)
    }

    // --- User Profile State ---
    private val _userProfile = MutableStateFlow<UserProfile?>(null)
    val userProfile = _userProfile.asStateFlow()

    private val _trackedSlotsByRoom = MutableStateFlow<List<RoomWithTrackedSlots>>(emptyList())
    val trackedSlotsByRoom = _trackedSlotsByRoom.asStateFlow()

    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    private val _integrationMessage = MutableStateFlow<String?>(null)
    val integrationMessage = _integrationMessage.asStateFlow()

    val isAutoSyncEnabled = settingsManager.isAutoSyncEnabled.stateIn(
        viewModelScope,
        SharingStarted.Eagerly,
        true
    )

    // --- Ignore List & Sorting State ---
    private val _ignoreList = MutableStateFlow<List<IgnoreItem>>(emptyList())
    val ignoreList = _ignoreList.asStateFlow()

    private val _knownGames = MutableStateFlow<List<String>>(emptyList())
    val knownGames = _knownGames.asStateFlow()

    private val _ignoreSortOption = MutableStateFlow(IgnoreSortOption.NEWEST)
    val ignoreSortOption = _ignoreSortOption.asStateFlow()

    init {
        fetchUserProfile()
        fetchTrackedSlots()
        fetchIgnoreList()
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
                _userProfile.value = RetrofitClient.instance.getUserProfile()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to load user profile."
                e.printStackTrace()
            }
        }
    }

    fun fetchTrackedSlots() {
        viewModelScope.launch {
            try {
                _trackedSlotsByRoom.value = RetrofitClient.instance.getUserTrackedSlots()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to load tracked slots."
                e.printStackTrace()
                _trackedSlotsByRoom.value = emptyList()
            }
        }
    }

    fun updateGlobalPreferences(
        progression: Boolean? = null,
        useful: Boolean? = null,
        hints: Boolean? = null,
        remoteHints: Boolean? = null,
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
            try {
                // 1. Find the current state of the slot from your local list
                //    This ensures we preserve existing overrides instead of resetting them.
                val currentRoom = _trackedSlotsByRoom.value.find { it.room_db_id == roomId }
                val currentSlot = currentRoom?.tracked_slots?.find { it.slot_id == slotId }

                if (currentSlot == null) {
                    // Safety check: If data is missing, don't attempt an update
                    return@launch
                }

                // 2. Construct the request using the NEW value for the target key,
                //    and the EXISTING values for everything else.
                val request = UpdateSlotPrefsRequest(
                    notify_progression = if (key == "notify_progression") value else currentSlot.notify_progression,
                    notify_useful = if (key == "notify_useful") value else currentSlot.notify_useful,
                    notify_hints = if (key == "notify_hints") value else currentSlot.notify_hints,
                    notify_hints_remote_items = if (key == "notify_hints_remote_items") value else currentSlot.notify_hints_remote_items,
                    notify_finished = if (key == "notify_finished") value else currentSlot.notify_finished,
                    combine_notifications = if (key == "combine_notifications") value else currentSlot.combine_notifications,
                    suppress_own_events = if (key == "suppress_own_events") value else currentSlot.suppress_own_events,
                    remove_emojis = if (key == "remove_emojis") value else currentSlot.remove_emojis,
                    suppress_self_found = if (key == "suppress_self_found") value else currentSlot.suppress_self_found,
                    use_condensed_messages = if (key == "use_condensed_messages") value else currentSlot.use_condensed_messages,
                    suppress_connected = if (key == "suppress_connected") value else currentSlot.suppress_connected
                )

                // 3. Send the complete update object
                val response = RetrofitClient.instance.updateSlotPreferences(roomId, slotId, request)

                if (response.isSuccessful) {
                    fetchTrackedSlots() // Refresh UI with new state
                } else {
                    _errorMessage.value = "Failed to update settings: ${response.code()}"
                }
            } catch (e: Exception) {
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

    // ============================================================================================
    // IGNORE LIST LOGIC
    // ============================================================================================

    fun fetchIgnoreList() {
        viewModelScope.launch {
            try {
                _ignoreList.value = userRepository.getIgnoreList()
            } catch (e: Exception) {
                Log.e("UserViewModel", "Failed to fetch ignore list", e)
                _errorMessage.value = "Failed to load ignore list."
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

    fun addIgnoreItem(itemName: String, gameName: String?) {
        viewModelScope.launch {
            try {
                userRepository.addIgnoreItem(itemName, gameName)
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

    fun updateIgnoreItem(id: Int, itemName: String, gameName: String?) {
        viewModelScope.launch {
            try {
                val request = com.jones.aptracker.network.AddIgnoreItemRequest(itemName, gameName)
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
}