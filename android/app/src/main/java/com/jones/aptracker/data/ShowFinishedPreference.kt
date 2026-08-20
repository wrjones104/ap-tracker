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
     * Deliberately NOT gated on `contains(KEY)`. HistoryViewModel seeds that key from
     * `ui_show_finished_default` on its first successful profile fetch, and it does so for
     * every user, so the key's presence says nothing about the user having chosen the
     * value -- it only says the app has been online once. Gating on it made this migration
     * unreachable for the entire existing install base, and since the old slots flag
     * defaulted to hiding finished slots while the unified one defaults to showing them,
     * that silently flipped My Slots on upgrade. Exactly the flip this exists to prevent.
     *
     * [legacyValue] is non-null only when the user explicitly tapped the old slots-screen
     * switch (the DataStore flow is `Flow<Boolean?>` and null no-ops upstream), so it is
     * a real choice and wins over a server-seeded default.
     *
     * It comes in as a parameter rather than being read here because DataStore reads are
     * suspending.
     *
     * @return true when the legacy value was applied, so the caller can sync it to the
     *   server -- the unified toggle is account-wide and would otherwise stay device-local
     *   until the user next touched it by hand.
     */
    fun migrateLegacyValue(context: Context, legacyValue: Boolean): Boolean {
        val p = prefs(context)
        if (p.getBoolean(KEY_LEGACY_MIGRATED, false)) return false

        p.edit {
            putBoolean(KEY, legacyValue)
            putBoolean(KEY_LEGACY_MIGRATED, true)
        }
        _value.value = legacyValue
        initialized = true
        return true
    }
}
