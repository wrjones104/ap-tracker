package com.jones.aptracker.network

import android.content.Context
import com.jones.aptracker.database.AppDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch

/**
 * Manages the global session state and handles the "self-destruct"
 * logout sequence when a 401 error is detected.
 */
object SessionManager {

    private lateinit var tokenManager: TokenManager
    private lateinit var appDatabase: AppDatabase

    private val _logoutEvent = MutableSharedFlow<Unit>()
    val logoutEvent = _logoutEvent.asSharedFlow()

    fun init(context: Context) {
        tokenManager = TokenManager(context)
        appDatabase = AppDatabase.getInstance(context)
    }

    /**
     * This is the "self-destruct" function. It clears all local user
     * data and notifies the UI to go back to the Login screen.
     */
    fun logout() {
        CoroutineScope(Dispatchers.IO).launch {
            tokenManager.deleteToken()

            appDatabase.clearAllTables()

            _logoutEvent.emit(Unit)
        }
    }
}