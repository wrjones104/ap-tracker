package com.jones.aptracker.ui

import androidx.lifecycle.ViewModel
import com.jones.aptracker.network.TokenManager
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import android.content.Context
import android.util.Log
import androidx.lifecycle.viewModelScope // This import is correct
import com.google.firebase.messaging.FirebaseMessaging
import com.jones.aptracker.network.RegisterDeviceRequest
import com.jones.aptracker.network.RetrofitClient
import kotlinx.coroutines.launch

class AuthViewModel : ViewModel() { // <-- Class starts here
    private val _isLoggedIn = MutableStateFlow(false)
    val isLoggedIn = _isLoggedIn.asStateFlow()

    private val _isLoading = MutableStateFlow(false)
    val isLoading = _isLoading.asStateFlow()

    fun setLoading(isLoading: Boolean) {
        _isLoading.value = isLoading
    }

    fun checkAuthStatus(tokenManager: TokenManager) {
        _isLoggedIn.value = tokenManager.getToken() != null
    }

    fun onLoginSuccess() {
        _isLoggedIn.value = true
    }

    fun onLogout() {
        _isLoggedIn.value = false
    }

    // --- FIX: FUNCTION MOVED INSIDE THE CLASS ---
    fun registerDeviceToken(context: Context) {
        val tokenManager = TokenManager(context) // Assuming TokenManager needs context
        // Only proceed if user is actually logged in (has an auth token)
        if (tokenManager.getToken() == null) {
            Log.w("AuthViewModel", "User not logged in. Cannot register FCM token.")
            return
        }

        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
            if (!task.isSuccessful) {
                Log.w("AuthViewModel", "Fetching FCM registration token failed", task.exception)
                return@addOnCompleteListener
            }

            val fcmToken = task.result
            Log.d("AuthViewModel", "FCM Token retrieved: $fcmToken. Sending to server...")

            // Now this will work because it's inside the ViewModel
            viewModelScope.launch {
                try {
                    val request = RegisterDeviceRequest(fcm_token = fcmToken)
                    // Make sure RetrofitClient is initialized before calling instance
                    val response = RetrofitClient.instance.registerDevice(request)
                    if (response.isSuccessful) {
                        Log.i("AuthViewModel", "FCM token registered with backend successfully.")
                    } else {
                        Log.e("AuthViewModel", "Backend FCM registration failed: ${response.code()} - ${response.errorBody()?.string()}")
                    }
                } catch (e: Exception) {
                    Log.e("AuthViewModel", "Error sending FCM token to server", e)
                    // Optional: Show a user-facing error message?
                }
            }
        }
    }
} // <-- Class ends here. The function is now inside.