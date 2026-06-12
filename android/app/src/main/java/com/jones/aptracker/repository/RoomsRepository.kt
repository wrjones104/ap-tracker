// In com.jones.aptracker.repository.RoomsRepository.kt

package com.jones.aptracker.repository

import android.content.Context
import android.util.Log
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.network.AddRoomRequest
import com.jones.aptracker.network.ApiService
import com.jones.aptracker.network.RoomDao
import com.jones.aptracker.network.RoomEntity
import kotlinx.coroutines.flow.Flow
import androidx.core.content.edit

class RoomsRepository(
    private val apiService: ApiService,
    private val roomDao: RoomDao,
    private val context: Context
) {

    val allRooms: Flow<List<RoomEntity>> = roomDao.getAllRooms()

    suspend fun refreshRooms() {
        val networkRooms = apiService.getRooms()

        val localRooms = roomDao.getAllRoomsOneShot()
        
        // Realignment Step: If any room's database ID changed, migrate history items, hints, and watermarks
        try {
            val db = AppDatabase.getInstance(context)
            val historyDao = db.historyDao()
            val hintDao = db.hintDao()
            val prefs = context.getSharedPreferences("ap_tracker_sync_watermarks", Context.MODE_PRIVATE)

            val allKeys = prefs.all
            val localRoomMap = localRooms.associateBy { it.room_id }

            networkRooms.forEach { networkRoom ->
                val localRoom = localRoomMap[networkRoom.room_id]
                if (localRoom != null && localRoom.id != networkRoom.id) {
                    val oldId = localRoom.id
                    val newId = networkRoom.id
                    Log.d("ALIGNMENT_DEBUG", "refreshRooms: Mismatch detected for room ${localRoom.alias} (UUID: ${localRoom.room_id})!")
                    Log.d("ALIGNMENT_DEBUG", "  Local ID: $oldId, Server ID: $newId. Re-aligning...")

                    // 1. Update roomId in history_items
                    historyDao.updateRoomIdForHistory(oldId, newId)

                    // 2. Update roomDbId in hints
                    hintDao.updateRoomIdForHints(oldId, newId)

                    // 3. Migrate SharedPreferences watermarks for all slots of this room!
                    prefs.edit {
                        allKeys.forEach { (key, value) ->
                            if (key.startsWith("item_watermark_${oldId}_")) {
                                val slotIdStr = key.substringAfter("item_watermark_${oldId}_")
                                val newItemKey = "item_watermark_${newId}_$slotIdStr"
                                if (value is String) {
                                    putString(newItemKey, value)
                                    remove(key)
                                }
                            }
                        }
                        
                        // Migrate hint watermark
                        val oldHintKey = "hint_watermark_$oldId"
                        val newHintKey = "hint_watermark_$newId"
                        if (prefs.contains(oldHintKey)) {
                            val ts = prefs.getString(oldHintKey, null)
                            putString(newHintKey, ts)
                            remove(oldHintKey)
                        }
                    }
                    Log.d("ALIGNMENT_DEBUG", "  Re-alignment from refreshRooms completed successfully.")
                }
            }
        } catch (e: Exception) {
            Log.e("ALIGNMENT_DEBUG", "Failed to realign room IDs in refreshRooms: ${e.message}", e)
        }

        val sortOrderMap = localRooms.associate { it.room_id to it.sort_order }
        var nextSortOrder = (localRooms.maxOfOrNull { it.sort_order } ?: 0) + 1

        val roomEntities = networkRooms.map { networkRoom ->
            val currentOrder = sortOrderMap[networkRoom.room_id]
            val finalOrder = currentOrder ?: nextSortOrder++

            RoomEntity(
                id = networkRoom.id,
                room_id = networkRoom.room_id,
                alias = networkRoom.alias,
                host = networkRoom.host,
                tracked_slots_count = networkRoom.tracked_slots_count,
                total_slots_count = networkRoom.total_slots_count,
                icon_name = networkRoom.icon_name,
                sort_order = finalOrder,
                is_archived = networkRoom.is_archived,
                is_suspended = networkRoom.is_suspended,
                status = networkRoom.status,
                web_url = networkRoom.web_url
            )
        }
        roomDao.syncRooms(roomEntities)
    }

    suspend fun updateRoomOrder(rooms: List<RoomEntity>) {
        roomDao.updateRooms(rooms)
    }

    suspend fun addRoom(request: AddRoomRequest) {
        val response = apiService.addRoom(request)
        if (!response.isSuccessful) throw Exception("Failed to add room")
        refreshRooms()
    }

    suspend fun refreshArchivedRooms(): List<com.jones.aptracker.network.Room> {
        return apiService.getRooms(archived = true)
    }

    suspend fun reviveRoom(roomId: Int) {
        val response = apiService.reviveRoom(roomId)
        if (!response.isSuccessful) throw Exception("Failed to revive room")
        refreshRooms()
    }
}