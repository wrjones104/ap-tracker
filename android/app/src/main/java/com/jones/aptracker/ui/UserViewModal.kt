package com.jones.aptracker.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.UserProfile
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

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
}