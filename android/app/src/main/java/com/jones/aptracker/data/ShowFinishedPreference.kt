package com.jones.aptracker.data

import android.content.Context
import androidx.core.content.edit
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * The single "show finished slots" toggle, shared by every surface that has one.
 *
 * The slots list used to keep its own local-only DataStore flag while the history feed
 * and the widgets used the server-synced `ui_show_finished`, so the same switch in two
 * places disagreed and only one of them followed the user to a new device. They are now
 * one preference.
 *
 * It lives here rather than in either ViewModel because both HistoryViewModel and
 * UserViewModel read and write it, and two independent StateFlows over the same
 * SharedPreferences key would drift the moment one screen changed it -- the other would
 * keep showing the stale value until it was recreated.
 */
object ShowFinishedPreference {

    private const val PREFS_NAME = FinishedDefinitionStore.PREFS_NAME
    private const val KEY = "ui_show_finished"

    /** Marks that the superseded slots-screen-only flag has already been carried over. */
    private const val KEY_LEGACY_MIGRATED = "slots_show_finished_migrated"

    private const val DEFAULT = true

    private val _value = MutableStateFlow(DEFAULT)
    val value: StateFlow<Boolean> = _value.asStateFlow()

    @Volatile
    private var initialized = false

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    /** Load the stored value into the flow. Safe to call from every ViewModel's init. */
    fun ensureLoaded(context: Context) {
        if (initialized) return
        synchronized(this) {
            if (initialized) return
            _value.value = prefs(context).getBoolean(KEY, DEFAULT)
            initialized = true
        }
    }

    fun get(context: Context): Boolean {
        ensureLoaded(context)
        return _value.value
    }

    /**
     * Write the toggle locally. The server sync is the caller's job -- UserViewModel owns
     * the preferences endpoint -- so this stays usable from paths that have no network.
     */
    fun set(context: Context, show: Boolean) {
        prefs(context).edit { putBoolean(KEY, show) }
        _value.value = show
        initialized = true
    }

    /**
     * Carry the old slots-screen-only value over, once.
     *
     * Only applies when the unified key has never been written, so a user who had the
     * shared toggle set already keeps it. Without this, anyone who had turned finished
     * slots on (or off) just for the slots list would see it silently flip on upgrade.
     *
     * [legacyValue] comes from the DataStore flow, which is why this takes it as a
     * parameter rather than reading it here -- DataStore reads are suspending.
     */
    fun migrateLegacyValue(context: Context, legacyValue: Boolean) {
        val p = prefs(context)
        if (p.getBoolean(KEY_LEGACY_MIGRATED, false)) return
        if (!p.contains(KEY)) {
            p.edit {
                putBoolean(KEY, legacyValue)
                putBoolean(KEY_LEGACY_MIGRATED, true)
            }
            _value.value = legacyValue
        } else {
            p.edit { putBoolean(KEY_LEGACY_MIGRATED, true) }
        }
        initialized = true
    }
}
