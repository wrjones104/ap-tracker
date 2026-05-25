package com.jones.aptracker.repository

import android.util.Log
import com.jones.aptracker.network.ApiService
import com.jones.aptracker.network.HintDao
import com.jones.aptracker.network.HintDetail
import com.jones.aptracker.network.HintEntity
import com.jones.aptracker.network.HistoryDao
import com.jones.aptracker.network.HistoryItemEntity
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.network.RoomEntity
import kotlinx.coroutines.flow.Flow

class HistoryRepository(
    private val apiService: ApiService,
    private val historyDao: HistoryDao,
    private val hintDao: HintDao,
    private val context: android.content.Context
) {
    private val prefs = context.getSharedPreferences("ap_tracker_sync_watermarks", android.content.Context.MODE_PRIVATE)
    suspend fun getHistoryForRoom(roomId: Int): List<HistoryItemEntity> {
        return historyDao.getHistoryForRoom(roomId)
    }

    suspend fun getHistoryForRoomPaged(roomId: Int, limit: Int, offset: Int): List<HistoryItemEntity> {
        return historyDao.getHistoryForRoomPaged(roomId, limit, offset)
    }

    suspend fun getGlobalHistory(): List<HistoryItemEntity> {
        return historyDao.getGlobalHistory()
    }

    suspend fun getGlobalHistoryPaged(limit: Int, offset: Int): List<HistoryItemEntity> {
        return historyDao.getGlobalHistoryPaged(limit, offset)
    }

    suspend fun realignRoomIdsIfMismatched(trackedRooms: List<com.jones.aptracker.network.RoomWithTrackedSlots>) {
        val roomDao = AppDatabase.getInstance(context).roomDao()
        trackedRooms.forEach { serverRoom ->
            val serverRoomId = serverRoom.room_db_id
            val roomUuid = serverRoom.room_id // Invariant UUID string from server!
            
            // Check if we have this room locally by UUID
            val localRoom = roomDao.getRoomByUuid(roomUuid)
            if (localRoom != null && localRoom.id != serverRoomId) {
                val oldId = localRoom.id
                Log.d("ALIGNMENT_DEBUG", "Mismatch detected for room ${localRoom.alias} (UUID: $roomUuid)!")
                Log.d("ALIGNMENT_DEBUG", "  Local ID: $oldId, Server ID: $serverRoomId. Re-aligning...")
                
                // 1. Delete the old room row and insert the updated room row in local DB
                roomDao.deleteRoomById(oldId)
                roomDao.insertOrUpdateRooms(listOf(localRoom.copy(id = serverRoomId)))
                
                // 2. Update roomId in history_items
                historyDao.updateRoomIdForHistory(oldId, serverRoomId)
                
                // 3. Update roomDbId in hints
                hintDao.updateRoomIdForHints(oldId, serverRoomId)
                
                // 4. Migrate SharedPreferences watermarks for all slots of this room!
                val prefsEdit = prefs.edit()
                // Migrate item watermarks
                serverRoom.tracked_slots.forEach { slot ->
                    val oldItemKey = "item_watermark_${oldId}_${slot.slot_id}"
                    val newItemKey = "item_watermark_${serverRoomId}_${slot.slot_id}"
                    if (prefs.contains(oldItemKey)) {
                        val ts = prefs.getString(oldItemKey, null)
                        prefsEdit.putString(newItemKey, ts)
                        prefsEdit.remove(oldItemKey)
                    }
                }
                // Migrate hint watermark
                val oldHintKey = "hint_watermark_$oldId"
                val newHintKey = "hint_watermark_$serverRoomId"
                if (prefs.contains(oldHintKey)) {
                    val ts = prefs.getString(oldHintKey, null)
                    prefsEdit.putString(newHintKey, ts)
                    prefsEdit.remove(oldHintKey)
                }
                
                // Save migration record for ViewModels to align their in-memory state
                prefsEdit.putInt("room_id_migration_${oldId}", serverRoomId)
                
                prefsEdit.apply()
                Log.d("ALIGNMENT_DEBUG", "  Re-alignment completed successfully.")
            }
        }
    }

    suspend fun syncHistoryBatch(trackedRooms: List<com.jones.aptracker.network.RoomWithTrackedSlots>) {
        Log.d("HISTORY_DEBUG", "Starting batch history sync...")
        
        try {
            realignRoomIdsIfMismatched(trackedRooms)
        } catch (e: Exception) {
            Log.e("HISTORY_DEBUG", "Failed to align room IDs: ${e.message}", e)
        }

        var hasMoreData = true
        var loopCount = 0
        val maxLoops = 25 // Safeguard limit against infinite loops
        
        while (hasMoreData && loopCount < maxLoops) {
            val itemWatermarks = mutableListOf<com.jones.aptracker.network.SlotSyncWatermark>()
            val hintWatermarks = mutableListOf<com.jones.aptracker.network.RoomSyncWatermark>()

            trackedRooms.forEach { room ->
                val roomId = room.room_db_id

                val hintKey = "hint_watermark_$roomId"
                val lastHintUpd = prefs.getString(hintKey, null)
                hintWatermarks.add(com.jones.aptracker.network.RoomSyncWatermark(roomId, lastHintUpd))

                room.tracked_slots.forEach { slot ->
                    val slotId = slot.slot_id
                    val itemKey = "item_watermark_${roomId}_$slotId"
                    val lastItemTs = prefs.getString(itemKey, null)
                    itemWatermarks.add(com.jones.aptracker.network.SlotSyncWatermark(roomId, slotId, lastItemTs))
                }
            }

            try {
                val request = com.jones.aptracker.network.HistorySyncRequest(itemWatermarks, hintWatermarks)
                val response = apiService.syncHistory(request)

                Log.d("HISTORY_DEBUG", "Sync Loop $loopCount: ${response.new_items.size} new items, ${response.updated_hints.size} updated hints.")

                if (response.new_items.isEmpty() && response.updated_hints.isEmpty()) {
                    hasMoreData = false
                    break
                }

                if (response.new_items.isNotEmpty()) {
                    val entities = response.new_items.mapNotNull { item ->
                        try {
                            HistoryItemEntity(
                                id = item.id,
                                roomId = item.room_db_id,
                                playerName = item.playerName,
                                playerAlias = item.playerAlias,
                                receivingGame = item.receivingGame,
                                itemName = item.itemName,
                                senderName = item.senderName,
                                senderAlias = item.senderAlias,
                                senderGame = item.senderGame,
                                locationName = item.locationName,
                                isPlayerFinished = item.isPlayerFinished,
                                itemFlags = item.itemFlags,
                                timestamp = normalizeTimestamp(item.timestamp),
                                tracker_id = item.tracker_id,
                                slot_id = item.slot_id,
                                icon_name = item.icon_name,
                                host = item.host,
                                receivedCount = item.receivedCount
                            )
                        } catch (e: Exception) {
                            Log.e("HISTORY_DEBUG", "!!! FAILED to process sync item: ${e.message}")
                            null
                        }
                    }
                    if (entities.isNotEmpty()) {
                        historyDao.insertHistoryItems(entities)
                    }
                }

                if (response.updated_hints.isNotEmpty()) {
                    val trackedSlotIds = itemWatermarks.map { it.slot_id }.toSet()
                    val entities = response.updated_hints.map { detail ->
                        val type = if (detail.item_owner_id in trackedSlotIds) "for_you" else "by_you"
                        mapHintDetailToEntity(detail, type)
                    }
                    if (entities.isNotEmpty()) {
                        hintDao.insertHints(entities)
                    }
                }

                // Persist new watermarks immediately to allow the next loop to fetch next batch
                prefs.edit().apply {
                    response.item_watermarks.forEach { (key, timestamp) ->
                        putString("item_watermark_$key", timestamp)
                    }
                    response.hint_watermarks.forEach { (key, timestamp) ->
                        putString("hint_watermark_$key", timestamp)
                    }
                }.apply()

                // If both lists are below limits, it means we fully caught up
                if (response.new_items.size < 200 && response.updated_hints.size < 100) {
                    hasMoreData = false
                }

            } catch (e: Exception) {
                Log.e("HISTORY_DEBUG", "!!! FAILED sync loop $loopCount: ${e.message}", e)
                throw e
            }
            
            loopCount++
        }
        
        Log.d("HISTORY_DEBUG", "Batch sync successfully completed in $loopCount loops and all history is complete.")
    }

    // --- ITEM HISTORY (Safe to use 'since' optimization) ---
    suspend fun refreshItemHistory() {
        Log.d("HISTORY_DEBUG", "Starting ITEM history refresh...")
        val latestTimestamp = historyDao.getLatestGlobalTimestamp()
        val limit = 50
        var offset = 0
        var fetchedCount = limit

        try {
            while (fetchedCount == limit) {
                val newItems = apiService.getGlobalItemHistory(since = latestTimestamp, limit = limit, offset = offset)
                fetchedCount = newItems.size
                Log.d("HISTORY_DEBUG", "Received $fetchedCount new items from the API (since $latestTimestamp, offset $offset).")

                if (newItems.isNotEmpty()) {
                    val entities = newItems.mapNotNull { item ->
                        try {
                            HistoryItemEntity(
                                id = item.id,
                                roomId = item.room_db_id,
                                playerName = item.playerName,
                                playerAlias = item.playerAlias,
                                receivingGame = item.receivingGame,
                                itemName = item.itemName,
                                senderName = item.senderName,
                                senderAlias = item.senderAlias,
                                senderGame = item.senderGame,
                                locationName = item.locationName,
                                isPlayerFinished = item.isPlayerFinished,
                                itemFlags = item.itemFlags,
                                timestamp = normalizeTimestamp(item.timestamp),
                                tracker_id = item.tracker_id,
                                slot_id = item.slot_id,
                                icon_name = item.icon_name,
                                host = item.host,
                                receivedCount = item.receivedCount
                            )
                        } catch (e: Exception) {
                            Log.e("HISTORY_DEBUG", "!!! FAILED to process history item: ${e.message}")
                            null
                        }
                    }
                    if (entities.isNotEmpty()) {
                        historyDao.insertHistoryItems(entities)
                    }
                }
                offset += fetchedCount
            }
        } catch (e: Exception) {
            Log.e("HISTORY_DEBUG", "!!! FAILED item history refresh: ${e.message}", e)
        }
    }

    // --- HINT FLOWS ---
    fun getHintsForRoom(roomId: Int, type: String): Flow<List<HintEntity>> {
        return hintDao.getAllHintsForRoom(roomId, type)
    }

    fun getGlobalHints(type: String): Flow<List<HintEntity>> {
        return hintDao.getAllGlobalHints(type)
    }

    // --- HINT REFRESH (Always Full Sync to catch Status Updates) ---
    suspend fun refreshHintHistory(roomId: Int? = null) {
        // We purposefully pass `since = null` here.
        // If we used a timestamp, we would miss hints that were created long ago
        // but were recently marked as "Found", because their creation timestamp didn't change.
        //
        // We also always pass `includeFound = true` to ensure the local DB
        // gets updated with the correct "found" status of existing hints,
        // even if the user has chosen to hide found hints in the UI.

        try {
            val response = if (roomId != null) {
                apiService.getRoomHintHistory(roomId, since = null, includeFound = true)
            } else {
                apiService.getGlobalHintHistory(since = null, includeFound = true)
            }

            Log.d("HINT_DEBUG", "Received ${response.hints_for_you.size} 'for_you' and ${response.hints_by_you.size} 'by_you' hints.")

            val entitiesToInsert = mutableListOf<HintEntity>()

            response.hints_for_you.mapTo(entitiesToInsert) { detail ->
                mapHintDetailToEntity(detail, "for_you")
            }
            response.hints_by_you.mapTo(entitiesToInsert) { detail ->
                mapHintDetailToEntity(detail, "by_you")
            }

            if (entitiesToInsert.isNotEmpty()) {
                // OnConflictStrategy.REPLACE ensures the old 'Unfound' record is overwritten
                // by this new 'Found' record, even if the ID is the same.
                hintDao.insertHints(entitiesToInsert)
                Log.d("HINT_DEBUG", "Insertion/Update complete.")
            }
        } catch (e: Exception) {
            Log.e("HINT_DEBUG", "!!! FAILED hint history refresh: ${e.message}", e)
        }
    }


    private fun mapHintDetailToEntity(detail: HintDetail, type: String): HintEntity {
        return HintEntity(
            hint_db_id = detail.id,
            roomDbId = detail.room_db_id,
            roomAlias = detail.room_alias,
            hintType = type,
            itemOwnerName = detail.item_owner_name,
            itemOwnerAlias = detail.item_owner_alias,
            locationOwnerName = detail.location_owner_name,
            locationOwnerAlias = detail.location_owner_alias,
            itemOwnerId = detail.item_owner_id,
            locationOwnerId = detail.location_owner_id,
            itemName = detail.item_name,
            locationName = detail.location_name,
            isFound = detail.is_found,
            timestamp = normalizeTimestamp(detail.timestamp),
            itemFlags = detail.item_flags
        )
    }

    suspend fun clearAllHistory() {
        Log.d("PRUNING", "Clearing all history and hints")
        try {
            historyDao.deleteAllHistory()
            hintDao.deleteAllHints()
        } catch (e: Exception) {
            Log.e("PRUNING", "Failed to clear all history: ${e.message}", e)
            throw e
        }
    }

    suspend fun pruneSlotData(roomId: Int, slotIds: Set<Int>) {
        if (slotIds.isEmpty()) return
        Log.d("PRUNING", "Pruning data for room $roomId, slots: $slotIds")
        try {
            historyDao.deleteHistoryForSlots(roomId, slotIds)
            hintDao.deleteHintsForSlots(roomId, slotIds)
            
            // Clear SharedPreferences watermarks for pruned slots!
            prefs.edit().apply {
                slotIds.forEach { slotId ->
                    remove("item_watermark_${roomId}_$slotId")
                }
            }.apply()
            Log.d("PRUNING", "Cleared SharedPreferences watermarks for pruned slots in room $roomId.")
        } catch (e: Exception) {
            Log.e("PRUNING", "Failed to prune slot data: ${e.message}", e)
        }
    }
}

private fun normalizeTimestamp(rawTime: String): String {
    var cleanString = rawTime.trim()

    if (cleanString.contains(" ") && !cleanString.contains("T")) {
        cleanString = cleanString.replace(" ", "T")
    }

    val hasTimeZone = cleanString.endsWith("Z") ||
            (cleanString.indexOfAny(charArrayOf('+', '-'), 10) != -1)

    if (!hasTimeZone) {
        cleanString += "Z"
    }

    return cleanString
}