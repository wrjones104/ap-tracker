package com.jones.aptracker.repository

import android.util.Log
import com.jones.aptracker.network.ApiService
import com.jones.aptracker.network.HintDao
import com.jones.aptracker.network.HintDetail
import com.jones.aptracker.network.HintEntity
import com.jones.aptracker.network.HistoryDao
import com.jones.aptracker.network.HistoryItem
import com.jones.aptracker.network.HistoryItemEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine

class HistoryRepository(
    private val apiService: ApiService,
    private val historyDao: HistoryDao,
    private val hintDao: HintDao
) {
    suspend fun getHistoryForRoom(roomId: Int): List<HistoryItemEntity> {
        return historyDao.getHistoryForRoom(roomId) 
    }

    suspend fun getGlobalHistory(): List<HistoryItemEntity> {
        return historyDao.getGlobalHistory()
    }

    suspend fun refreshItemHistory() {
        Log.d("HISTORY_DEBUG", "Starting ITEM history refresh...")
        val latestTimestamp = historyDao.getLatestGlobalTimestamp()
        try {
            val newItems = apiService.getGlobalItemHistory(since = latestTimestamp)
            Log.d("HISTORY_DEBUG", "Received ${newItems.size} new items from the API.")
            if (newItems.isNotEmpty()) {
                val entities = newItems.mapNotNull { item ->
                    try {
                        val entity = HistoryItemEntity(
                            roomId = item.db_id,
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
                            host = item.host
                        )
                        Log.d("HISTORY_DEBUG", "Successfully parsed item: ${entity.playerName} received ${entity.itemName}")
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

    suspend fun getHintsForRoom(roomId: Int, includeFound: Boolean): Pair<List<HintEntity>, List<HintEntity>> {
        Log.d("HintToggleDebug", "Repo: getHintsForRoom (DAO Read) | includeFound: $includeFound")

        val hintsForYou = if (includeFound) {
            hintDao.getAllHintsForRoom(roomId, "for_you")
        } else {
            hintDao.getUnfoundHintsForRoom(roomId, "for_you")
        }

        val hintsByYou = if (includeFound) {
            hintDao.getAllHintsForRoom(roomId, "by_you")
        } else {
            hintDao.getUnfoundHintsForRoom(roomId, "by_you")
        }

        return Pair(hintsForYou, hintsByYou)
    }

    suspend fun getGlobalHints(includeFound: Boolean): Pair<List<HintEntity>, List<HintEntity>> {
        Log.d("HintToggleDebug", "Repo: getGlobalHints (DAO Read) | includeFound: $includeFound")

        val hintsForYou = if (includeFound) {
            hintDao.getAllGlobalHints("for_you")
        } else {
            hintDao.getUnfoundGlobalHints("for_you")
        }

        val hintsByYou = if (includeFound) {
            hintDao.getAllGlobalHints("by_you")
        } else {
            hintDao.getUnfoundGlobalHints("by_you")
        }

        return Pair(hintsForYou, hintsByYou)
    }

    suspend fun refreshHintHistory(roomId: Int? = null, includeFound: Boolean) {
        Log.d("HINT_SYNC", "Forcing full hint refresh (since=null)")

        try {
            // Pass null for 'since' to fetch everything
            val response = if (roomId != null) {
                apiService.getRoomHintHistory(roomId, since = null, includeFound = includeFound)
            } else {
                apiService.getGlobalHintHistory(since = null, includeFound = includeFound)
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
                // Because DAO uses OnConflictStrategy.REPLACE, this will update isFound status
                // for existing hints and insert new ones.
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
    suspend fun pruneSlotData(roomId: Int, slotIds: Set<Int>) {
        if (slotIds.isEmpty()) return
        Log.d("PRUNING", "Pruning data for room $roomId, slots: $slotIds")
        try {
            historyDao.deleteHistoryForSlots(roomId, slotIds)
            hintDao.deleteHintsForSlots(roomId, slotIds)
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