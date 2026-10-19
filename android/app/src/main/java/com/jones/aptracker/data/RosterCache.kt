package com.jones.aptracker.data

import android.content.Context
import android.util.Log
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.jones.aptracker.network.RoomWithTrackedSlots
import java.io.File

/**
 * The last tracked-slots roster the Activity screen loaded, kept on disk (#468).
 *
 * The screen needs the roster (active rooms, aliases, finish state) before it can show the
 * phone's history, and on a cold start it used to wait on GET /users/me/tracked-slots for it.
 * With this copy it paints at once and reconciles when the server answers. The HTTP cache from
 * #417 cannot serve here: the server marks that response no-cache, which OkHttp refuses to
 * serve without asking the server, even for an only-if-cached request.
 *
 * Lives in the cache directory and is deleted on logout, like the rest of the account's data.
 */
object RosterCache {

    private const val TAG = "RosterCache"
    private const val FILE_NAME = "activity_roster.json"

    private val gson = Gson()
    private val rosterType = object : TypeToken<List<RoomWithTrackedSlots>>() {}.type

    private fun file(context: Context) = File(context.applicationContext.cacheDir, FILE_NAME)

    fun save(context: Context, rooms: List<RoomWithTrackedSlots>) {
        try {
            val target = file(context)
            val tmp = File(target.parentFile, "$FILE_NAME.tmp")
            tmp.writeText(encode(rooms))
            if (!tmp.renameTo(target)) {
                target.delete()
                tmp.renameTo(target)
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to save the roster", e)
        }
    }

    /** The saved roster, or null when there is none or it cannot be read. */
    fun load(context: Context): List<RoomWithTrackedSlots>? =
        try {
            val f = file(context)
            if (f.exists()) decode(f.readText()) else null
        } catch (e: Exception) {
            Log.w(TAG, "Failed to read the roster", e)
            null
        }

    fun clear(context: Context) {
        file(context).delete()
    }

    internal fun encode(rooms: List<RoomWithTrackedSlots>): String = gson.toJson(rooms, rosterType)

    internal fun decode(json: String): List<RoomWithTrackedSlots>? =
        try {
            gson.fromJson<List<RoomWithTrackedSlots>>(json, rosterType)
        } catch (e: Exception) {
            null
        }
}
