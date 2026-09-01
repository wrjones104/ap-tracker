package com.jones.aptracker.network

import android.content.Context
import android.util.Log
import com.google.firebase.messaging.FirebaseMessaging
import com.jones.aptracker.database.AppDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import java.util.concurrent.atomic.AtomicBoolean

object SessionManager {

    private lateinit var tokenManager: TokenManager
    private lateinit var appDatabase: AppDatabase

    private val _logoutEvent = MutableSharedFlow<LogoutReason>()
    val logoutEvent = _logoutEvent.asSharedFlow()

    private val isLoggingOut = AtomicBoolean(false)

    enum class LogoutReason {
        USER_REQUEST,
        SESSION_EXPIRED
    }

    fun init(context: Context) {
        tokenManager = TokenManager(context)
        appDatabase = AppDatabase.getInstance(context)
    }

    fun logout(reason: LogoutReason) {
        // Wrap the logout logic in the compareAndSet check
        if (isLoggingOut.compareAndSet(false, true)) {
            CoroutineScope(Dispatchers.IO).launch {
                tokenManager.deleteToken()
                appDatabase.clearAllTables()

                _logoutEvent.emit(reason)

                // Only the user-initiated logout in AuthViewModel can call DELETE /devices,
                // since that endpoint needs a valid token. A forced logout (SESSION_EXPIRED)
                // has none, so the device would keep its server-side registration and keep
                // receiving pushes forever. Invalidating the FCM token instead makes the next
                // push come back UNREGISTERED, which the poller already prunes. See #308.
                //
                // Runs after the logout event so navigation is not held up by the network.
                try {
                    FirebaseMessaging.getInstance().deleteToken().await()
                } catch (e: Exception) {
                    Log.e("SessionManager", "Failed to invalidate FCM token during logout.", e)
                }
            }
        }
    }

    // Added a way to reset the lock when the user logs back in
    fun resetLogoutState() {
        isLoggingOut.set(false)
    }
}