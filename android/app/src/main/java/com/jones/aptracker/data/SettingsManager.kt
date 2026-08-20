package com.jones.aptracker.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "settings")

class SettingsManager(context: Context) {

    private val dataStore = context.dataStore

    companion object {
        val CHEESE_AUTO_SYNC_KEY = booleanPreferencesKey("cheese_auto_sync")
        val IS_CHEESE_CONNECTED_KEY = booleanPreferencesKey("is_cheese_connected")
        val DATE_FORMAT_PRESET_KEY = stringPreferencesKey("date_format_preset")
        val SLOTS_SHOW_FINISHED_KEY = booleanPreferencesKey("slots_show_finished")
        val EXPANDED_ROOM_IDS_KEY = stringPreferencesKey("expanded_room_ids")
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
     * A flow that emits the current date format preset.
     * It defaults to 'SYSTEM_DEFAULT' if not set.
     */
    val dateFormatPreset: Flow<String> = dataStore.data
        .map { preferences ->
            preferences[DATE_FORMAT_PRESET_KEY] ?: "SYSTEM_DEFAULT"
        }

    /**
     * The superseded slots-screen-only "show finished" flag.
     *
     * Read once at startup so [com.jones.aptracker.data.ShowFinishedPreference] can carry
     * the user's choice onto the unified, server-synced toggle. Nothing writes it any
     * more -- do not reintroduce a setter, or the two would diverge again.
     */
    val slotsShowFinished: Flow<Boolean?> = dataStore.data
        .map { preferences ->
            // Nullable on purpose. The migration must not treat "never set" as an explicit
            // false: this flag defaulted to false while the unified toggle defaults to
            // true, so carrying over a phantom false would silently hide finished slots
            // for users who never touched it.
            preferences[SLOTS_SHOW_FINISHED_KEY]
        }

    /**
     * A flow that emits the set of expanded room DB IDs.
     */
    val expandedRoomIds: Flow<Set<Int>> = dataStore.data
        .map { preferences ->
            try {
                val raw = preferences[EXPANDED_ROOM_IDS_KEY] ?: ""
                if (raw.isBlank()) emptySet()
                else raw.split(",").mapNotNull { it.trim().toIntOrNull() }.toSet()
            } catch (e: Exception) {
                emptySet()
            }
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

    /**
     * Saves the new date format preset preference.
     */
    suspend fun setDateFormatPreset(preset: String) {
        dataStore.edit { preferences ->
            preferences[DATE_FORMAT_PRESET_KEY] = preset
        }
    }

    /**
     * Saves the expanded room IDs.
     */
    suspend fun setExpandedRoomIds(roomIds: Set<Int>) {
        dataStore.edit { preferences ->
            preferences[EXPANDED_ROOM_IDS_KEY] = roomIds.joinToString(",")
        }
    }
}