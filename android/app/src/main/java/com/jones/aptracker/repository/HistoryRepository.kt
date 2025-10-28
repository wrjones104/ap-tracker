package com.jones.aptracker.repository

import android.util.Log
import com.jones.aptracker.network.* // Ensure new Hint classes/DAO are imported
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine // Import combine

class HistoryRepository(
    private val apiService: ApiService,
    private val historyDao: HistoryDao,
    private val hintDao: HintDao // --- ADD HINT DAO ---
) {
    // --- Item History (Existing) ---
    fun getHistoryForRoom(roomId: Int): Flow<List<HistoryItemEntity>> {
        return historyDao.getHistoryForRoom(roomId)
    }

    fun getGlobalHistory(): Flow<List<HistoryItemEntity>> {
        return historyDao.getGlobalHistory()
    }

    suspend fun refreshItemHistory() { // Renamed for clarity
        Log.d("HISTORY_DEBUG", "Starting ITEM history refresh...")
        val latestTimestamp = historyDao.getLatestGlobalTimestamp()
        try {
            val newItems = apiService.getGlobalItemHistory(since = latestTimestamp)
            Log.d("HISTORY_DEBUG", "Received ${newItems.size} new items from the API.")
            if (newItems.isNotEmpty()) {
                val entities = newItems.mapNotNull { item ->
                    try {
                        // --- THE FIX: Safely handle potential nulls ---
                        val entity = HistoryItemEntity(
                            roomId = item.db_id, // roomId is already nullable
                            message = item.message,
                            timestamp = item.timestamp,
                            tracker_id = item.tracker_id, // tracker_id is already nullable
                            slot_id = item.slot_id,     // slot_id is already nullable
                            icon_name = item.icon_name  // icon_name is already nullable
                        )
                        Log.d("HISTORY_DEBUG", "Successfully parsed item: ${entity.message}")
                        entity
                    } catch (e: Exception) {
                        Log.e("HISTORY_DEBUG", "!!! FAILED to process history item. Error: ${e.message}")
                        Log.e("HISTORY_DEBUG", "Problematic Item Data: $item")
                        null
                    }
                }
                if (entities.isNotEmpty()) {
                    Log.d("HISTORY_DEBUG", "Inserting ${entities.size} new item entities.")
                    historyDao.insertHistoryItems(entities)
                }
            }
        } catch (e: Exception) {
            Log.e("HISTORY_DEBUG", "!!! FAILED item history refresh: ${e.message}", e)
        }
    }
    // Existing mapping code from previous snippet
    private fun mapHistoryItemToEntity(item: HistoryItem): HistoryItemEntity? {
        return try {
            HistoryItemEntity(
                roomId = item.db_id,
                message = item.message,
                timestamp = item.timestamp,
                tracker_id = item.tracker_id,
                slot_id = item.slot_id,
                icon_name = item.icon_name
            )
        } catch (e: Exception) {
            Log.e("HISTORY_DEBUG", "Failed to process history item: $item", e)
            null
        }
    }


    // --- Hint History (New) ---

    // --- MODIFIED: Added includeFound param ---
    fun getHintsForRoom(roomId: Int, includeFound: Boolean): Flow<Pair<List<HintEntity>, List<HintEntity>>> {
        // --- NEW: Explicitly convert Boolean to Int ---
        val includeFoundInt = if (includeFound) 1 else 0

        // --- MODIFIED: Pass Int to DAO ---
        val hintsForYou = hintDao.getHintsForRoom(roomId, "for_you", includeFoundInt)
        val hintsByYou = hintDao.getHintsForRoom(roomId, "by_you", includeFoundInt)
        return combine(hintsForYou, hintsByYou) { forYou, byYou -> Pair(forYou, byYou) }
    }

    // --- MODIFIED: Added includeFound param ---
    fun getGlobalHints(includeFound: Boolean): Flow<Pair<List<HintEntity>, List<HintEntity>>> {
        // --- NEW: Explicitly convert Boolean to Int ---
        val includeFoundInt = if (includeFound) 1 else 0

        // --- MODIFIED: Pass Int to DAO ---
        val hintsForYou = hintDao.getGlobalHints("for_you", includeFoundInt)
        val hintsByYou = hintDao.getGlobalHints("by_you", includeFoundInt)
        return combine(hintsForYou, hintsByYou) { forYou, byYou -> Pair(forYou, byYou) }
    }

    // --- MODIFIED: Added includeFound param ---
    suspend fun refreshHintHistory(roomId: Int? = null, includeFound: Boolean) {
        Log.d("HINT_DEBUG", "Starting HINT history refresh... (Room: ${roomId ?: "Global"}, Found: $includeFound)")
        val latestTimestamp = if (roomId != null) {
            hintDao.getLatestTimestampForRoom(roomId)
        } else {
            hintDao.getLatestGlobalTimestamp()
        }

        try {
            val response = if (roomId != null) {
                // --- MODIFIED: Pass param to API service ---
                apiService.getRoomHintHistory(roomId, since = latestTimestamp, includeFound = includeFound)
            } else {
                // --- MODIFIED: Pass param to API service ---
                apiService.getGlobalHintHistory(since = latestTimestamp, includeFound = includeFound)
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
                Log.d("HINT_DEBUG", "Inserting ${entitiesToInsert.size} new hint entities.")
                hintDao.insertHints(entitiesToInsert)
            }
        } catch (e: Exception) {
            Log.e("HINT_DEBUG", "!!! FAILED hint history refresh: ${e.message}", e)
        }
    }

    // Helper function to map API response to DB entity
    private fun mapHintDetailToEntity(detail: HintDetail, type: String): HintEntity {
        return HintEntity(
            hint_db_id = detail.id,
            roomDbId = detail.room_db_id,
            roomAlias = detail.room_alias,
            hintType = type,
            itemOwnerName = detail.item_owner_name,
            locationOwnerName = detail.location_owner_name,
            itemName = detail.item_name,
            locationName = detail.location_name,
            isFound = detail.is_found,
            timestamp = detail.timestamp
        )
    }
}