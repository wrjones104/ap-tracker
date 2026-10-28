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
import androidx.core.content.edit
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull

class HistoryRepository(
    private val apiService: ApiService,
    private val historyDao: HistoryDao,
    private val hintDao: HintDao,
    private val context: android.content.Context
) {
    private val prefs = context.getSharedPreferences("ap_tracker_sync_watermarks", android.content.Context.MODE_PRIVATE)
    private val syncMutex = Mutex()
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
                // And the hint coverage stored pushes earned, with the slots it was earned for
                migratePushCoverage(prefs, oldId, serverRoomId) { key, value ->
                    prefsEdit.putString(key, value)
                }.forEach { prefsEdit.remove(it) }
                
                // Save migration record for ViewModels to align their in-memory state
                prefsEdit.putInt("room_id_migration_${oldId}", serverRoomId)
                
                prefsEdit.apply()
                Log.d("ALIGNMENT_DEBUG", "  Re-alignment completed successfully.")
            }
        }
    }

    suspend fun syncHistoryBatch(
        trackedRooms: List<com.jones.aptracker.network.RoomWithTrackedSlots>,
        priorityRoomId: Int? = null,
        onBatchReceived: (suspend (itemsFetchedThisBatch: Int, loopCount: Int, hasMore: Boolean) -> Unit)? = null
    ) {
        Log.d("HISTORY_DEBUG", "Starting batch history sync (priority room: ${priorityRoomId ?: "None"})...")
        
        syncMutex.withLock {
            try {
                realignRoomIdsIfMismatched(trackedRooms)
            } catch (e: Exception) {
                Log.e("HISTORY_DEBUG", "Failed to align room IDs: ${e.message}", e)
            }

            val sortedRooms = if (priorityRoomId != null) {
                trackedRooms.sortedByDescending { it.room_db_id == priorityRoomId }
            } else {
                trackedRooms
            }

            var hasMoreData = true
            var loopCount = 0
            val maxLoops = 100 // Allow up to 100 loops (20,000 items) to fully catch up
            
            while (hasMoreData && loopCount < maxLoops) {
                val itemWatermarks = mutableListOf<com.jones.aptracker.network.SlotSyncWatermark>()
                val hintWatermarks = mutableListOf<com.jones.aptracker.network.RoomSyncWatermark>()

                sortedRooms.forEach { room ->
                    val roomId = room.room_db_id

                    val hintKey = "hint_watermark_$roomId"
                    val lastHintUpd = prefs.getString(hintKey, null)
                    hintWatermarks.add(com.jones.aptracker.network.RoomSyncWatermark(roomId, lastHintUpd))

                    room.tracked_slots.forEach { slot ->
                        val slotId = slot.slot_id
                        val maxLocalId = historyDao.getMaxIdForSlot(roomId, slotId)
                        itemWatermarks.add(com.jones.aptracker.network.SlotSyncWatermark(roomId, slotId, last_id = maxLocalId))
                    }
                }

                try {
                    val request = com.jones.aptracker.network.HistorySyncRequest(itemWatermarks, hintWatermarks)
                    val response = apiService.syncHistory(request)

                    Log.d("HISTORY_DEBUG", "Sync Loop $loopCount: ${response.new_items.size} new items, ${response.updated_hints.size} updated hints.")

                    val isBatchEmpty = response.new_items.isEmpty() && response.updated_hints.isEmpty()
                    if (isBatchEmpty) {
                        hasMoreData = false
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
                                    playerHasAllChecks = item.playerHasAllChecks,
                                    itemFlags = item.itemFlags,
                                    timestamp = normalizeTimestamp(item.timestamp),
                                    tracker_id = item.tracker_id,
                                    slot_id = item.slot_id,
                                    icon_name = item.icon_name,
                                    host = item.host,
                                    receivedCount = item.receivedCount,
                                    isIgnored = item.isIgnored,
                                    isWhitelisted = item.isWhitelisted
                                )
                            } catch (e: Exception) {
                                Log.e("HISTORY_DEBUG", "!!! FAILED to process sync item: ${e.message}")
                                null
                            }
                        }
                        if (entities.isNotEmpty()) {
                            historyDao.insertHistoryItems(entities)

                            // Prune stale pre-purge records for affected slots if local max ID far exceeds server's returned IDs
                            entities.groupBy { (it.roomId ?: 0) to (it.slot_id ?: 0) }.forEach { (key, slotEntities) ->
                                val (rId, sId) = key
                                if (rId > 0 && sId > 0) {
                                    val maxNewServerId = slotEntities.maxOfOrNull { it.id } ?: 0L
                                    val localMaxId = historyDao.getMaxIdForSlot(rId, sId)?.toLong()
                                    if (localMaxId != null && localMaxId > maxNewServerId + 1000) {
                                        Log.w("HISTORY_DEBUG", "Stale local history detected for room $rId, slot $sId (localMax=$localMaxId, newMax=$maxNewServerId). Pruning stale items...")
                                        historyDao.deleteHistoryForSlotAboveId(rId, sId, maxNewServerId)
                                    }
                                }
                            }
                        }
                    }

                    if (response.updated_hints.isNotEmpty()) {
                        // Per room, as the server decides it: slot numbers restart in every room,
                        // so a bare slot id would file a hint by another room's tracked slot.
                        // The History screen re-derives the type from the live tracked slots
                        // anyway (classifyHints); this keeps the stored value honest.
                        val trackedPairs = itemWatermarks.map { it.room_db_id to it.slot_id }.toSet()
                        val entities = response.updated_hints.map { detail ->
                            val type = if ((detail.room_db_id to detail.item_owner_id) in trackedPairs) "for_you" else "by_you"
                            mapHintDetailToEntity(detail, type)
                        }
                        if (entities.isNotEmpty()) {
                            hintDao.insertHints(entities)
                        }
                    }

                    // Persist new watermarks immediately to allow the next loop to fetch next batch
                    val hintCursors = hintCursorsToStore(
                        roomsSentWithoutCursor = hintWatermarks
                            .filter { it.last_updated == null }
                            .map { it.room_db_id.toString() }
                            .toSet(),
                        roomsInBatch = response.updated_hints.map { it.room_db_id.toString() }.toSet(),
                        serverCursors = response.hint_watermarks
                    )
                    prefs.edit {
                        response.item_watermarks.forEach { (key, value) ->
                            putString("item_watermark_$key", value.toString())
                        }
                        hintCursors.forEach { (key, timestamp) ->
                            putString("hint_watermark_$key", timestamp)
                        }
                    }

                    // Stream batch to UI immediately!
                    onBatchReceived?.invoke(response.new_items.size, loopCount + 1, hasMoreData && !isBatchEmpty)

                    if (isBatchEmpty) {
                        break
                    }

                } catch (e: Exception) {
                    Log.e("HISTORY_DEBUG", "!!! FAILED sync loop $loopCount: ${e.message}", e)
                    throw e
                }
                
                loopCount++
            }
            
            Log.d("HISTORY_DEBUG", "Batch sync successfully completed in $loopCount loops and all history is complete.")
        } // syncMutex.withLock
    }

    /**
     * One page of older items from the server, for when Activity scrolls past the local cache.
     *
     * Holds the sync mutex across the request and the insert, as syncHistoryBatch does (#481).
     * The rows are new to the cache and arrive flagged under the rules in force when the request
     * went out, and the re-flag after a rule change (refreshItemFilterFlags) only updates rows
     * already stored. Without the lock, a page requested before a rule change and stored after
     * its re-flag kept the old flags for good: the delta sync never re-sends those ids. With it,
     * either the re-flag runs after the insert and covers these rows, or the request goes out
     * after the change and the server flags them correctly. A page load can wait behind a batch
     * sync; it only runs once the local pages are used up.
     */
    suspend fun fetchItemHistoryFeed(roomId: Int?, limit: Int = 50, offset: Int = 0): List<HistoryItemEntity> = syncMutex.withLock {
        Log.d("HISTORY_DEBUG", "Fetching item history feed for room ${roomId ?: "Global"} (limit: $limit, offset: $offset)...")
        val items = if (roomId != null) {
            apiService.getItemHistory(roomId = roomId, limit = limit, offset = offset)
        } else {
            apiService.getGlobalItemHistory(limit = limit, offset = offset)
        }

        val entities = items.mapNotNull { item ->
            try {
                HistoryItemEntity(
                    id = item.id,
                    roomId = item.room_db_id ?: roomId,
                    playerName = item.playerName,
                    playerAlias = item.playerAlias,
                    receivingGame = item.receivingGame,
                    itemName = item.itemName,
                    senderName = item.senderName,
                    senderAlias = item.senderAlias,
                    senderGame = item.senderGame,
                    locationName = item.locationName,
                    isPlayerFinished = item.isPlayerFinished,
                    playerHasAllChecks = item.playerHasAllChecks,
                    itemFlags = item.itemFlags,
                    timestamp = normalizeTimestamp(item.timestamp),
                    tracker_id = item.tracker_id,
                    slot_id = item.slot_id,
                    icon_name = item.icon_name,
                    host = item.host,
                    receivedCount = item.receivedCount,
                    isIgnored = item.isIgnored,
                    isWhitelisted = item.isWhitelisted
                )
            } catch (e: Exception) {
                Log.e("HISTORY_DEBUG", "!!! FAILED to process history feed item: ${e.message}")
                null
            }
        }
        if (entities.isNotEmpty()) {
            historyDao.insertHistoryItems(entities)
        }
        entities
    }

    // --- PUSH PAYLOAD (#416) ---
    /**
     * Stores the items and hint changes a push carried, when nothing is missing between them and
     * what the phone already has ([pushPayloadApplies]). Returns false when it could not, and
     * the caller syncs instead.
     *
     * Holds the sync mutex, so the check and the writes cannot interleave with a sync's. Waits
     * for it only briefly: Firebase hands pushes over one at a time, so every push queued behind
     * this one would wait out a long sync too. Syncing instead costs one rerun of that sync.
     *
     * The writes are not one transaction, and need not be: coverage is written last, so a store
     * cut short leaves rows that the next sync replaces and coverage that never claimed them.
     */
    suspend fun applyPushPayload(payload: PushPayload): Boolean {
        withTimeoutOrNull(PUSH_LOCK_WAIT_MS) { syncMutex.lock() } ?: return false
        return try {
            storePushPayload(payload)
        } finally {
            syncMutex.unlock()
        }
    }

    private suspend fun storePushPayload(payload: PushPayload): Boolean {
        val localMaxIdBySlot = payload.slots.keys.associateWith { slotId ->
            historyDao.getMaxIdForSlot(payload.roomId, slotId)?.toLong()
        }
        val coverageKey = hintPushCoverageKey(payload.roomId)
        val trackedKeyKey = hintPushCoverageTrackedKey(payload.roomId)
        val pushCoverage = pushCoverageStillCounts(
            prefs.getString(coverageKey, null), prefs.getString(trackedKeyKey, null), payload
        )
        val hintCoverage = laterCursor(prefs.getString("hint_watermark_${payload.roomId}", null), pushCoverage)
        if (!pushPayloadApplies(payload, localMaxIdBySlot, hintCoverage)) return false

        // Only what is new to the phone: a push that arrives after a sync must not put back older
        // values (itemsToStore, hintsToStore).
        val items = itemsToStore(payload.toItemEntities(), localMaxIdBySlot)
        if (items.isNotEmpty()) historyDao.insertHistoryItems(items)
        val allHints = payload.toHintEntities()
        val hints = if (allHints.isEmpty()) allHints
            else hintsToStore(allHints, hintDao.getFoundHintIds(allHints.map { it.hint_db_id }))
        if (hints.isNotEmpty()) hintDao.insertHints(hints)

        // The sync's own hint cursor is left alone: the next sync re-sends these hints, which
        // replaces them with the same values. Coverage only moves forward while the tracked slots
        // stay the same, so a push that arrives late cannot move it back; it starts over when they
        // change (pushCoverageStillCounts).
        pushCoverageToStore(pushCoverage, payload)?.let { newest ->
            prefs.edit {
                putString(coverageKey, newest)
                putString(trackedKeyKey, trackedKey(payload.trackedSlots))
            }
        }
        return true
    }

    // --- HINT FLOWS ---
    // Every hint of the scope, whatever type was stored with it. The History screen splits them
    // into "for you" and "by you" from the slots tracked now (classifyHints).
    fun getHintsForRoom(roomId: Int): Flow<List<HintEntity>> {
        return hintDao.getAllHintsForRoom(roomId)
    }

    fun getGlobalHints(): Flow<List<HintEntity>> {
        return hintDao.getAllGlobalHints()
    }

    // --- FULL HINT DOWNLOAD (repair only) ---
    // Every hint touching a tracked slot, found or not, re-sent whole. The delta sync
    // (syncHistoryBatch) already carries new hints and found-status changes, because the server
    // bumps updated_at when a hint is found. So this runs only where the delta cannot help:
    // a refresh the user asked for, and after an ignore or whitelist rule change, which
    // re-flags hints without touching updated_at. It used to run on every push and every
    // periodic sync, and was most of the app's data use (#411).
    suspend fun refreshHintHistory(roomId: Int? = null) {
        // `includeFound = true` so the local DB gets the found status of every hint,
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
        } catch (e: CancellationException) {
            // A superseded filter repair: let it stop here rather than fall through to the
            // item re-flag that follows it in requestFilterRepair.
            throw e
        } catch (e: Exception) {
            Log.e("HINT_DEBUG", "!!! FAILED hint history refresh: ${e.message}", e)
        }
    }


    // --- ITEM RE-FLAG (after a rule change, #464) ---
    /**
     * Re-flags every cached item from the server's current answer. isIgnored and isWhitelisted
     * are decided when an item is sent and the delta sync never re-sends it, so without this a
     * rule only ever applied to items received after it.
     *
     * Holds the sync mutex, so neither writer of items (syncHistoryBatch and the paged feed,
     * fetchItemHistoryFeed, both of which hold it across their network calls) can store items
     * flagged under the old rules between the fetch and the apply, and one in flight during a
     * rule change finishes before this corrects it (#481). Returns true when the cache was
     * re-flagged; false on a server without the route (404) or any failure, which leaves the
     * flags as they were.
     */
    suspend fun refreshItemFilterFlags(): Boolean = syncMutex.withLock {
        try {
            val flags = apiService.getHistoryFilterFlags()
            historyDao.applyFilterFlags(flags.ignored_ids.orEmpty(), flags.whitelisted_ids.orEmpty())
            Log.d("HISTORY_DEBUG", "Re-flagged items: ${flags.ignored_ids.orEmpty().size} ignored, ${flags.whitelisted_ids.orEmpty().size} whitelisted.")
            true
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.w("HISTORY_DEBUG", "Item re-flag skipped: ${e.message}")
            false
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
            itemFlags = detail.item_flags,
            isIgnored = detail.isIgnored,
            isWhitelisted = detail.isWhitelisted
        )
    }

    suspend fun clearAllHistory() {
        Log.d("PRUNING", "Clearing all history and hints")
        try {
            historyDao.deleteAllHistory()
            hintDao.deleteAllHints()
            
            // Clear all watermarks from SharedPreferences but preserve v21 cleared flag
            prefs.edit().clear().putBoolean("watermarks_cleared_v21", true).apply()
            Log.d("PRUNING", "Cleared all SharedPreferences watermarks.")
        } catch (e: Exception) {
            Log.e("PRUNING", "Failed to clear all history: ${e.message}", e)
            throw e
        }
    }

    suspend fun getLocalItemCount(roomId: Int?): Int {
        return if (roomId != null) {
            historyDao.getItemCountForRoom(roomId)
        } else {
            historyDao.getTotalItemCount()
        }
    }

    suspend fun pruneSlotData(roomId: Int, slotIds: Set<Int>) {
        if (slotIds.isEmpty()) return
        Log.d("PRUNING", "Pruning data for room $roomId, slots: $slotIds")
        try {
            historyDao.deleteHistoryForSlots(roomId, slotIds)
            // Hints are kept. The delta sync stores every hint in the room, and the History
            // screen shows only those touching a slot tracked now (classifyHints). Deleting
            // here also took hints shared with a slot still tracked, and since #411 only a
            // reset of the room's hint cursor, re-downloading the whole room, brought them back.
            
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

    companion object {
        // How long a push waits for a running sync before syncing instead (applyPushPayload).
        private const val PUSH_LOCK_WAIT_MS = 1_000L

        @Volatile
        private var INSTANCE: HistoryRepository? = null

        fun getInstance(context: android.content.Context): HistoryRepository {
            return INSTANCE ?: synchronized(this) {
                val instance = INSTANCE ?: run {
                    val appContext = context.applicationContext
                    val db = com.jones.aptracker.database.AppDatabase.getInstance(appContext)
                    val apiService = com.jones.aptracker.network.RetrofitClient.instance
                    HistoryRepository(apiService, db.historyDao(), db.hintDao(), appContext)
                }.also { INSTANCE = it }
                instance
            }
        }
    }
}

/**
 * The hint cursors worth storing from one /history/sync answer, keyed by room db id.
 *
 * The server answers "now" for a room that sent no cursor and got no hints back, even when other
 * rooms' older hints filled the 100-hint batch (#421). Storing that would skip the room's whole
 * hint history, so such a room keeps an empty cursor until its hints arrive. A room that really
 * has no hints just asks again from the start, which returns nothing. The full hint download on
 * every sync used to paper over this, before #411.
 */
internal fun hintCursorsToStore(
    roomsSentWithoutCursor: Set<String>,
    roomsInBatch: Set<String>,
    serverCursors: Map<String, String?>
): Map<String, String?> = serverCursors.filterKeys { room ->
    room !in roomsSentWithoutCursor || room in roomsInBatch
}

/** Where a room's hint coverage from stored pushes is kept, beside its sync cursors. */
internal fun hintPushCoverageKey(roomId: Int) = "hint_push_coverage_$roomId"

/** The tracked slots that coverage was earned for (see pushCoverageStillCounts). */
internal fun hintPushCoverageTrackedKey(roomId: Int) = "hint_push_coverage_tracked_$roomId"

/**
 * Copies a room's push coverage keys to its new db id through [put], for the two places that
 * realign a room's id. Returns the old keys, for the caller to remove in the same edit.
 */
internal fun migratePushCoverage(
    prefs: android.content.SharedPreferences,
    oldId: Int,
    newId: Int,
    put: (String, String?) -> Unit
): List<String> = listOf(
    hintPushCoverageKey(oldId) to hintPushCoverageKey(newId),
    hintPushCoverageTrackedKey(oldId) to hintPushCoverageTrackedKey(newId)
).filter { (old, _) -> prefs.contains(old) }.map { (old, new) ->
    put(new, prefs.getString(old, null))
    old
}

internal fun normalizeTimestamp(rawTime: String): String {
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