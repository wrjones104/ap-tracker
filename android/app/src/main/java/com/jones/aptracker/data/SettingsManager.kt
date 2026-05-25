package com.jones.aptracker.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "settings")

class SettingsManager(context: Context) {

    private val dataStore = context.dataStore

    companion object {
        val CHEESE_AUTO_SYNC_KEY = booleanPreferencesKey("cheese_auto_sync")
        val IS_CHEESE_CONNECTED_KEY = booleanPreferencesKey("is_cheese_connected")
    }

    /**
     * A flow that emits the current auto-sync preference.
     * It defaults to 'true' (auto-sync on) if not set.
     */
    val isAutoSyncEnabled: Flow<Boolean> = dataStore.data
        .map { preferences ->
            preferences[CHEESE_AUTO_SYNC_KEY] ?: true
        }

    /**
     * A flow that emits whether Cheese Tracker is connected.
     * It defaults to 'false' if not set.
     */
    val isCheeseConnected: Flow<Boolean> = dataStore.data
        .map { preferences ->
            preferences[IS_CHEESE_CONNECTED_KEY] ?: false
        }

    /**
     * Saves the new auto-sync preference.
     */
    suspend fun setAutoSync(isEnabled: Boolean) {
        dataStore.edit { preferences ->
            preferences[CHEESE_AUTO_SYNC_KEY] = isEnabled
        }
    }

    /**
     * Saves whether Cheese Tracker is connected.
     */
    suspend fun setCheeseConnected(isConnected: Boolean) {
        dataStore.edit { preferences ->
            preferences[IS_CHEESE_CONNECTED_KEY] = isConnected
        }
    }
}