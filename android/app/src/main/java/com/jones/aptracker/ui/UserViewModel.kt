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
import com.jones.aptracker.network.UpdateGlobalPrefsRequest
import com.jones.aptracker.network.UpdateSlotPrefsRequest
import com.jones.aptracker.network.UserProfile
import com.jones.aptracker.repository.UserRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import retrofit2.HttpException

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

    // Default to Newest, will be overwritten by loadSortPreference() in init
    private val _ignoreSortOption = MutableStateFlow(IgnoreSortOption.NEWEST)
    val ignoreSortOption = _ignoreSortOption.asStateFlow()

    init {
        fetchUserProfile()
        fetchTrackedSlots()
        fetchIgnoreList()
        loadSortPreference() // Load saved sort order on startup
    }

    // ============================================================================================
    // PREFERENCES & SORTING
    // ============================================================================================

    fun setAutoSync(isEnabled: Boolean) {
        viewModelScope.launch {
            settingsManager.setAutoSync(isEnabled)
        }
    }

    /**
     * Updates the sort option in StateFlow and persists it to SharedPreferences
     */
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
        uiShowFinished: Boolean? = null,
        uiShowFoundHints: Boolean? = null
    ) {
        viewModelScope.launch {
            try {
                // Create a Map to ensure we ONLY send the fields that are changing.
                // This prevents Gson from sending "null" for the other fields,
                // which would accidentally turn them off.
                val params = mutableMapOf<String, Boolean>()

                progression?.let { params["notify_progression"] = it }
                useful?.let { params["notify_useful"] = it }
                hints?.let { params["notify_hints"] = it }
                remoteHints?.let { params["notify_hints_remote_items"] = it }
                finished?.let { params["notify_finished"] = it }
                useCondensed?.let { params["use_condensed_messages"] = it }

                // Map the camelCase arguments to the snake_case keys the API expects
                uiShowFinished?.let { params["ui_show_finished"] = it }
                uiShowFoundHints?.let { params["ui_show_found_hints"] = it }

                RetrofitClient.instance.updateUserPreferences(params)

                fetchUserProfile()

            } catch (e: Exception) {
                _errorMessage.value = "Failed to save preferences."
                e.printStackTrace()
            }
        }
    }

    fun updateSlotPreferences(
        roomId: Int,
        slotId: Int,
        progression: Boolean?,
        useful: Boolean?,
        hints: Boolean?,
        remoteHints: Boolean?,
        finished: Boolean?,
        useCondensed: Boolean?
    ) {
        viewModelScope.launch {
            try {
                val request = UpdateSlotPrefsRequest(
                    notify_progression = progression,
                    notify_useful = useful,
                    notify_hints = hints,
                    notify_hints_remote_items = remoteHints,
                    notify_finished = finished,
                    use_condensed_messages = useCondensed
                )
                RetrofitClient.instance.updateSlotPreferences(roomId, slotId, request)
                fetchTrackedSlots()
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
}