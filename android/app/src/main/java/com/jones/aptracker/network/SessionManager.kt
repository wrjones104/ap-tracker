package com.jones.aptracker.network

import android.content.Context
import com.jones.aptracker.database.AppDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
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
            }
        }
    }

    // Added a way to reset the lock when the user logs back in
    fun resetLogoutState() {
        isLoggingOut.set(false)
    }
}