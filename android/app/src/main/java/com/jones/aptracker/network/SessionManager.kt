package com.jones.aptracker.network

import android.content.Context
import com.jones.aptracker.database.AppDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch

object SessionManager {

    private lateinit var tokenManager: TokenManager
    private lateinit var appDatabase: AppDatabase

    private val _logoutEvent = MutableSharedFlow<LogoutReason>()
    val logoutEvent = _logoutEvent.asSharedFlow()

    enum class LogoutReason {
        USER_REQUEST,
        SESSION_EXPIRED
    }

    fun init(context: Context) {
        tokenManager = TokenManager(context)
        appDatabase = AppDatabase.getInstance(context)
    }
    fun logout(reason: LogoutReason) {
        CoroutineScope(Dispatchers.IO).launch {
            tokenManager.deleteToken()
            appDatabase.clearAllTables()

            _logoutEvent.emit(reason)
        }
    }
}