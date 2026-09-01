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
import com.jones.aptracker.data.SettingsManager
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

    private val _failedAuthAttempt = MutableStateFlow<Pair<String, String>?>(null)
    val failedAuthAttempt = _failedAuthAttempt.asStateFlow()

    private val _showMergeConflictDialog = MutableStateFlow(false)
    val showMergeConflictDialog = _showMergeConflictDialog.asStateFlow()

    fun startGuestUpgrade(context: Context, onAuth: () -> Unit) {
        viewModelScope.launch {
            try {
                val tokenManager = TokenManager(context)
                tokenManager.saveToken("")
            } catch (e: Exception) {
                Log.e("AuthViewModel", "Failed to clear token", e)
            }

            try {
                val settingsManager = SettingsManager(context)
                settingsManager.setAutoSync(false)
                settingsManager.setCheeseConnected(false)
            } catch (e: Exception) {
                Log.e("AuthViewModel", "Failed to clear settings", e)
            }

            onAuth()

            _isLoggedIn.value = false
        }
    }
    fun onMergeConflict(code: String, codeVerifier: String) {
        _failedAuthAttempt.value = code to codeVerifier
        _showMergeConflictDialog.value = true
    }

    fun clearMergeConflict() {
        _showMergeConflictDialog.value = false
        _failedAuthAttempt.value = null
    }

    fun setLoading(isLoading: Boolean) {
        _isLoading.value = isLoading
    }

    fun checkAuthStatus(tokenManager: TokenManager) {
        _isLoggedIn.value = tokenManager.getToken() != null
    }

    fun onLoginSuccess() {
        // Reset the 401 lockout state so it's ready for the new session
        SessionManager.resetLogoutState()
        _isLoggedIn.value = true
    }

    fun onLogout(context: Context) {
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

                 try {
                    val settingsManager = SettingsManager(context)
                    settingsManager.setAutoSync(false)
                    settingsManager.setCheeseConnected(false)
                    Log.d("AuthViewModel", "Cleared local auto-sync and cheese-connected settings.")
                } catch (e: Exception) {
                    Log.e("AuthViewModel", "Failed to clear SettingsManager.", e)
                }

                try {
                    SessionManager.logout(SessionManager.LogoutReason.USER_REQUEST)
                } catch (e: Exception) {
                    Log.e("AuthViewModel", "Failed to clear SessionManager.", e)
                }

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

        viewModelScope.launch {
            // A forced logout invalidates the FCM token on a detached coroutine. Fetching
            // before that finishes would hand the server the very token the pending delete
            // is about to destroy, leaving the device silently unreachable. Wait it out.
            SessionManager.awaitTokenInvalidation()

            val fcmToken = try {
                FirebaseMessaging.getInstance().token.await()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.w("AuthViewModel", "Fetching FCM registration token failed", e)
                return@launch
            }

            Log.d("AuthViewModel", "FCM Token retrieved: $fcmToken. Sending to server...")

            val androidId = Settings.Secure.getString(
                context.contentResolver,
                Settings.Secure.ANDROID_ID
            )

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
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.e("AuthViewModel", "Error sending FCM token to server", e)
            }
        }
    }
}