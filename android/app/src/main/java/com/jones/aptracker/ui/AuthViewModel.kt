package com.jones.aptracker.ui

import androidx.lifecycle.ViewModel
import com.jones.aptracker.network.TokenManager
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import android.content.Context
import android.util.Log
import androidx.lifecycle.viewModelScope // This import is correct
import com.google.firebase.messaging.FirebaseMessaging
// --- NEW: Import the new request object ---
import com.jones.aptracker.network.DeviceRegisterRequest
import com.jones.aptracker.network.RetrofitClient
import kotlinx.coroutines.launch
// --- NEW: Import Settings to get the Android ID ---
import android.provider.Settings

class AuthViewModel : ViewModel() {
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

    fun registerDeviceToken(context: Context) {
        val tokenManager = TokenManager(context)
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

            // --- NEW: Get the unique Android ID ---
            val androidId = Settings.Secure.getString(
                context.contentResolver,
                Settings.Secure.ANDROID_ID
            )

            // Now this will work because it's inside the ViewModel
            viewModelScope.launch {
                try {
                    // --- CHANGED: Use the new request object with both fields ---
                    val request = DeviceRegisterRequest(
                        fcm_token = fcmToken,
                        android_id = androidId
                    )

                    // Make sure RetrofitClient is initialized before calling instance
                    val response = RetrofitClient.instance.registerDevice(request)
                    if (response.isSuccessful) {
                        Log.i("AuthViewModel", "FCM token and Android ID registered with backend successfully.")
                    } else {
                        Log.e("AuthViewModel", "Backend FCM registration failed: ${response.code()} - ${response.errorBody()?.string()}")
                    }
                } catch (e: Exception) {
                    Log.e("AuthViewModel", "Error sending FCM token to server", e)
                }
            }
        }
    }
}