package com.jones.aptracker.ui

import android.app.Activity
import android.content.Context
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.data.SettingsManager
import com.jones.aptracker.network.SessionManager
import com.jones.aptracker.network.TokenManager
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.unifiedpush.android.connector.INSTANCE_DEFAULT
import org.unifiedpush.android.connector.UnifiedPush

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
            // --- UNIFIED PUSH UNREGISTRATION ---
            // This will trigger onUnregistered in NotificationHandler.
            try {
                UnifiedPush.unregister(context)
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
            Log.w("AuthViewModel", "User not logged in. Cannot register Unified Push Provider.")
            return
        }

        // --- UNIFIED PUSH REGISTRATION ---
        // This will trigger onNewEndpoint in NotificationHandler if a distributor is selected,
        // or onRegistrationFailed if VAPID is required or no distributor is found.
        try {
            UnifiedPush.tryUseDefaultDistributor(context) { success ->
                if (success) {
                    UnifiedPush.register(context, INSTANCE_DEFAULT, "test")
                }
            }
        } catch (e: Exception) {
            Log.e("AuthViewModel", "UnifiedPush registration failed to start", e)
        }
    }
}