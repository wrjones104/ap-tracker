package com.jones.aptracker.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.RoomWithTrackedSlots
import com.jones.aptracker.network.UpdateGlobalPrefsRequest
import com.jones.aptracker.network.UpdateSlotPrefsRequest
import com.jones.aptracker.network.UserProfile
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class UserViewModel : ViewModel() {
    private val _userProfile = MutableStateFlow<UserProfile?>(null)
    val userProfile = _userProfile.asStateFlow()
    private val _trackedSlotsByRoom = MutableStateFlow<List<RoomWithTrackedSlots>>(emptyList())
    val trackedSlotsByRoom = _trackedSlotsByRoom.asStateFlow()

    // --- NEW: Add the error message StateFlow ---
    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    init {
        fetchUserProfile()
        fetchTrackedSlots()
    }

    fun fetchUserProfile() {
        viewModelScope.launch {
            try {
                _userProfile.value = RetrofitClient.instance.getUserProfile()
            } catch (e: Exception) {
                // --- FIXED: Set error message ---
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
                // --- FIXED: Set error message ---
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
                // --- FIXED: Set error message ---
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
                // --- FIXED: Set error message ---
                _errorMessage.value = "Failed to save slot settings."
                e.printStackTrace()
            }
        }
    }

    // --- This function will now work correctly ---
    fun clearErrorMessage() {
        _errorMessage.value = null
    }
}