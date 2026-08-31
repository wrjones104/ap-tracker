package com.jones.aptracker.data

import androidx.compose.runtime.Immutable
import android.content.Context
import android.util.Log
import androidx.core.content.edit
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONObject

/**
 * Local mirror of the user's finished-definition preferences.
 *
 * Widgets run outside the app process with no ViewModel and no network call on their
 * load path, but they still have to hide finished slots the same way the app does.
 * They already read view preferences straight out of [PREFS_NAME], so the definitions
 * ride along in the same file: the global default as a string, and the per-slot
 * overrides as a small JSON map.
 *
 * Mirrored rather than denormalized onto each row on purpose. Changing the setting
 * re-evaluates everything already cached on the next read, with no rewrite of the
 * history table and no resync.
 */
object FinishedDefinitionStore {

    private const val TAG = "FinishedDefinitionStore"

    /** Shared with HistoryViewModel and the widgets. */
    const val PREFS_NAME = "ap_tracker_prefs"

    private const val KEY_DEFAULT = "finished_definition_default"
    private const val KEY_OVERRIDES = "finished_definition_overrides"

    private val _resolver = MutableStateFlow(FinishedResolver.GOAL_ONLY)

    /**
     * The current resolver, shared by every screen.
     *
     * A flow rather than a per-ViewModel snapshot so changing the setting re-filters
     * screens that are already loaded. Two independent snapshots would leave the history
     * feed showing the old definition until it happened to refetch.
     */
    val resolverFlow: StateFlow<FinishedResolver> = _resolver.asStateFlow()

    @Volatile
    private var initialized = false

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    /** Load the stored preferences into [resolverFlow]. Safe to call from every init. */
    fun ensureLoaded(context: Context) {
        if (initialized) return
        synchronized(this) {
            if (initialized) return
            _resolver.value = resolver(context)
            initialized = true
        }
    }

    private fun publish(context: Context) {
        _resolver.value = resolver(context)
        initialized = true
    }

    private fun overrideKey(roomDbId: Int, slotId: Int) = "$roomDbId:$slotId"

    /**
     * Snapshot the current preferences into a resolver.
     *
     * Read once per composition or filter pass rather than per row -- SharedPreferences
     * reads are cheap but the JSON parse is not, and the history feed evaluates this
     * across hundreds of items.
     */
    fun resolver(context: Context): FinishedResolver {
        val p = prefs(context)
        val default = FinishedDefinition.fromWire(p.getString(KEY_DEFAULT, null))

        val overrides = mutableMapOf<String, FinishedDefinition>()
        val raw = p.getString(KEY_OVERRIDES, null)
        if (!raw.isNullOrBlank()) {
            try {
                val json = JSONObject(raw)
                for (key in json.keys()) {
                    // optString returns "" for a missing or null entry, which fromWire
                    // would silently turn into the default -- skip instead, so an absent
                    // override stays absent rather than becoming a pinned one.
                    val value = json.optString(key)
                    if (value.isBlank()) continue
                    overrides[key] = FinishedDefinition.fromWire(value)
                }
            } catch (e: Exception) {
                // A corrupt map must not take the feed down; fall back to the default.
                Log.w(TAG, "Failed to parse finished definition overrides", e)
            }
        }
        return FinishedResolver(default, overrides)
    }

    fun writeDefault(context: Context, definition: FinishedDefinition) {
        prefs(context).edit { putString(KEY_DEFAULT, definition.wireValue) }
        publish(context)
    }

    /**
     * Replace the override map wholesale from the tracked-slot roster.
     *
     * Called after every tracked-slots fetch. Whole-map replacement rather than a merge
     * so a cleared override on the server actually disappears here -- a merge would
     * leave a stale entry pinning the slot to an override the user removed.
     *
     * [definitionsBySlot] is keyed by (roomDbId, slotId); a null value means the slot
     * has no override and inherits the default.
     */
    fun writeOverrides(context: Context, definitionsBySlot: Map<Pair<Int, Int>, String?>) {
        val json = JSONObject()
        for ((slot, value) in definitionsBySlot) {
            if (value.isNullOrBlank()) continue
            json.put(overrideKey(slot.first, slot.second), value)
        }
        prefs(context).edit { putString(KEY_OVERRIDES, json.toString()) }
        publish(context)
    }
}

/**
 * An immutable snapshot of the finished-definition preferences.
 *
 * Every "is this slot finished for this user" decision in the app goes through here,
 * so the answer cannot drift between the slot list, the history feed, and the widgets.
 */
/**
 * Marked immutable so Compose can skip composables that take one. Both fields are vals
 * assigned at construction and never mutated -- a new resolver is built rather than an
 * existing one edited. Without this, Compose treats the type as unstable and every
 * composable holding one recomposes unconditionally.
 */
@Immutable
class FinishedResolver(
    private val default: FinishedDefinition,
    private val overrides: Map<String, FinishedDefinition>
) {

    fun definitionFor(roomDbId: Int?, slotId: Int?): FinishedDefinition {
        if (roomDbId == null || slotId == null) return default
        return overrides["$roomDbId:$slotId"] ?: default
    }

    /**
     * Whether a slot reads as finished for this user.
     *
     * [hasAllChecks] null means the server has no check counts for the room, which
     * degrades every definition to goal-only. See [FinishedDefinition.evaluate].
     */
    fun isFinished(roomDbId: Int?, slotId: Int?, isGoaled: Boolean, hasAllChecks: Boolean?): Boolean =
        definitionFor(roomDbId, slotId).evaluate(isGoaled, hasAllChecks)

    companion object {
        /** Goal-only, for previews and for paths with no context to read preferences from. */
        val GOAL_ONLY = FinishedResolver(FinishedDefinition.DEFAULT, emptyMap())
    }
}
