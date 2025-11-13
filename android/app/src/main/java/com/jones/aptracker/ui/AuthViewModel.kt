package com.jones.aptracker.ui

import android.content.Context
import android.provider.Settings
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.google.firebase.messaging.FirebaseMessaging
import com.jones.aptracker.network.RegisterDeviceRequest
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.SessionManager
import com.jones.aptracker.network.TokenManager
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import kotlin.coroutines.cancellation.CancellationException

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
        viewModelScope.launch {
            val fcmToken = try {
                FirebaseMessaging.getInstance().token.await()
            } catch (e: Exception) {
                Log.e("AuthViewModel", "Failed to get FCM token.", e)
                null
            }

            try {
                if (fcmToken != null) {
                    val request = RegisterDeviceRequest(fcm_token = fcmToken)
                    RetrofitClient.instance.unregisterDevice(request)
                    Log.d("AuthViewModel", "Device unregistered from server.")
                }

                RetrofitClient.instance.logout()
                Log.d("AuthViewModel", "Token blocklisted on server.")

            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.e("AuthViewModel", "Failed to clear session on server. Proceeding with local logout.", e)
            } finally {
                SessionManager.logout()

                _isLoggedIn.value = false
            }
        }
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

            val androidId = Settings.Secure.getString(
                context.contentResolver,
                Settings.Secure.ANDROID_ID
            )

            viewModelScope.launch {
                try {
                    val request = RegisterDeviceRequest(
                        fcm_token = fcmToken,
                        android_id = androidId
                    )

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