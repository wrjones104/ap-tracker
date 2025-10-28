package com.jones.aptracker.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.UserProfile
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import com.jones.aptracker.network.UpdateGlobalPrefsRequest

class UserViewModel : ViewModel() {
    private val _userProfile = MutableStateFlow<UserProfile?>(null)
    val userProfile = _userProfile.asStateFlow()

    init {
        fetchUserProfile()
    }

    fun fetchUserProfile() {
        viewModelScope.launch {
            try {
                _userProfile.value = RetrofitClient.instance.getUserProfile()
            } catch (e: Exception) {
                e.printStackTrace()
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

                // Refresh the local profile data after saving
                fetchUserProfile()

            } catch (e: Exception) {
                // TODO: Show an error message to the user
                e.printStackTrace()
            }
        }
    }
}