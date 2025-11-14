package com.jones.aptracker.ui

import android.app.Application
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.data.SettingsManager
import com.jones.aptracker.network.CheeseAuthRequest
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.RoomWithTrackedSlots
import com.jones.aptracker.network.UpdateGlobalPrefsRequest
import com.jones.aptracker.network.UpdateSlotPrefsRequest
import com.jones.aptracker.network.UserProfile
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class UserViewModel(application: Application) : AndroidViewModel(application) {
    private val settingsManager = SettingsManager(application)
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

    fun setAutoSync(isEnabled: Boolean) {
        viewModelScope.launch {
            settingsManager.setAutoSync(isEnabled)
        }
    }

    init {
        fetchUserProfile()
        fetchTrackedSlots()
    }

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
        hints: Boolean? = null
    ) {
        viewModelScope.launch {
            try {
                val request = UpdateGlobalPrefsRequest(
                    notify_progression = progression,
                    notify_useful = useful,
                    notify_hints = hints
                )
                RetrofitClient.instance.updateUserPreferences(request)

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
        hints: Boolean?
    ) {
        viewModelScope.launch {
            try {
                val request = UpdateSlotPrefsRequest(
                    notify_progression = progression,
                    notify_useful = useful,
                    notify_hints = hints
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

    fun connectCheeseTracker(apiKey: String) {
        viewModelScope.launch {
            try {
                val response = RetrofitClient.instance.connectCheeseTracker(CheeseAuthRequest(apiKey))
                _integrationMessage.value = response.message
                fetchUserProfile()
                fetchTrackedSlots()
            } catch (e: Exception) {
                e.printStackTrace()
                _errorMessage.value = "Failed to connect to Cheese Tracker. Check your key."
            }
        }
    }
    private fun triggerBackgroundSync() {
        viewModelScope.launch {
            try {
                RetrofitClient.instance.syncCheeseTracker()
                fetchTrackedSlots()
            } catch (e: Exception) {
                e.printStackTrace()
                Log.w("UserViewModel", "Background sync failed: ${e.message}")
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

}