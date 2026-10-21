package com.jones.aptracker.data

import android.content.Context
import android.util.Log
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.jones.aptracker.BuildConfig
import com.jones.aptracker.network.RoomWithTrackedSlots
import com.jones.aptracker.network.SessionManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/**
 * The last tracked-slots roster the app loaded, kept on disk (#468).
 *
 * The Activity screen needs the roster (active rooms, aliases, finish state) before it can show
 * the phone's history, and on a cold start it used to wait on GET /users/me/tracked-slots for it.
 * With this copy it paints at once and reconciles when the server answers. The HTTP cache from
 * #417 cannot serve here: the server marks that response no-cache, which OkHttp refuses to
 * serve without asking the server, even for an only-if-cached request.
 *
 * The file name carries the app's version code. Gson fills a field missing from the JSON with
 * null even when the Kotlin type is non-null and has a default, so a roster saved by an older
 * build is never read by a newer one: the first cold start after an upgrade waits on the server.
 *
 * Lives in the cache directory and is deleted on logout, like the rest of the account's data.
 */
object RosterCache {

    private const val TAG = "RosterCache"
    private const val FILE_PREFIX = "activity_roster_"

    private val gson = Gson()
    private val rosterType = object : TypeToken<List<RoomWithTrackedSlots>>() {}.type

    private fun dir(context: Context): File = context.applicationContext.cacheDir

    fun save(context: Context, rooms: List<RoomWithTrackedSlots>) = save(dir(context), BuildConfig.VERSION_CODE, rooms)

    /**
     * [save] off the main thread, skipped once logout has begun: a roster load still in flight
     * when the user logs out must not write the old account's rooms back after logout cleared them.
     */
    suspend fun saveUnlessLoggingOut(context: Context, rooms: List<RoomWithTrackedSlots>) {
        if (SessionManager.logoutInProgress()) return
        withContext(Dispatchers.IO) { save(context, rooms) }
    }

    /** The saved roster, or null when there is none or it cannot be read. */
    fun load(context: Context): List<RoomWithTrackedSlots>? = load(dir(context), BuildConfig.VERSION_CODE)

    /** Deletes the roster saved by every app version, including copies left by older builds. */
    fun clear(context: Context) = clear(dir(context))

    internal fun fileName(versionCode: Int) = "$FILE_PREFIX$versionCode.json"

    internal fun save(dir: File, versionCode: Int, rooms: List<RoomWithTrackedSlots>) {
        try {
            val target = File(dir, fileName(versionCode))
            val tmp = File(dir, "${fileName(versionCode)}.tmp")
            tmp.writeText(encode(rooms))
            if (!tmp.renameTo(target)) {
                target.delete()
                tmp.renameTo(target)
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to save the roster", e)
        }
    }

    /**
     * A file that does not decode to a well-formed roster is deleted, not just skipped. It is only
     * rewritten after a successful network load, so leaving it would hand every cold start the
     * same bad copy until then (#483).
     */
    internal fun load(dir: File, versionCode: Int): List<RoomWithTrackedSlots>? =
        try {
            val f = File(dir, fileName(versionCode))
            if (!f.exists()) null else decode(f.readText()) ?: run { f.delete(); null }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to read the roster", e)
            null
        }

    internal fun clear(dir: File) {
        dir.listFiles { f -> f.name.startsWith(FILE_PREFIX) }?.forEach { it.delete() }
    }

    internal fun encode(rooms: List<RoomWithTrackedSlots>): String = gson.toJson(rooms, rosterType)

    internal fun decode(json: String): List<RoomWithTrackedSlots>? =
        try {
            gson.fromJson<List<RoomWithTrackedSlots>>(json, rosterType)?.takeIf { isWellFormed(it) }
        } catch (e: Exception) {
            null
        }

    /**
     * False when Gson left a non-null field null. It builds these classes without running their
     * constructors, so a field missing from the JSON comes back null whatever its Kotlin type
     * says, and nothing fails until a screen reads it while drawing. Both the Rooms and Activity
     * screens paint from this copy before the server answers (#468, #483).
     *
     * Covers every non-null reference field the two classes declare. Primitives cannot be null.
     */
    @Suppress("SENSELESS_COMPARISON")
    internal fun isWellFormed(rooms: List<RoomWithTrackedSlots>): Boolean = rooms.all { room ->
        room != null && room.room_id != null && room.room_alias != null &&
            room.icon_name != null && room.tracked_slots != null &&
            room.tracked_slots.all { slot ->
                slot != null && slot.player_name != null && slot.track_mode != null &&
                    (slot.cheese == null || slot.cheese.notes != null)
            }
    }
}
