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
                            receivingGame = item.receivingGame,
                            itemName = item.itemName,
                            senderName = item.senderName,
                            senderGame = item.senderGame,
                            locationName = item.locationName,
                            isPlayerFinished = item.isPlayerFinished,
                            itemFlags = item.itemFlags,
                            timestamp = item.timestamp,
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

        var performFullRefresh = false

        if (includeFound) {
            val foundCount = if (roomId != null) {
                hintDao.countFoundHints(roomId)
            } else {
                hintDao.countGlobalFoundHints()
            }

            if (foundCount == 0) {
                performFullRefresh = true
                Log.d("HINT_SYNC", "Cold Start detected: 'Show Found' enabled but 0 found hints in DB. Forcing full refresh.")
            }
        }

        val latestTimestamp = if (performFullRefresh) {
            null
        } else {
            if (roomId != null) {
                hintDao.getLatestTimestampForRoom(roomId)
            } else {
                hintDao.getLatestGlobalTimestamp()
            }
        }

        Log.d("HintToggleDebug", "Repo: API 'since' param will be: $latestTimestamp")
        try {
            val response = if (roomId != null) {
                apiService.getRoomHintHistory(roomId, since = latestTimestamp, includeFound = includeFound)
            } else {
                apiService.getGlobalHintHistory(since = latestTimestamp, includeFound = includeFound)
            }

            Log.d("HINT_DEBUG", "Received ${response.hints_for_you.size} 'for_you' and ${response.hints_by_you.size} 'by_you' hints.")

            if (response.hints_for_you.isNotEmpty()) {
                Log.d("HintToggleDebug", "Repo: First 'for_you' hint from API has is_found=${response.hints_for_you[0].is_found} (ID: ${response.hints_for_you[0].id})")
            }
            if (response.hints_by_you.isNotEmpty()) {
                Log.d("HintToggleDebug", "Repo: First 'by_you' hint from API has is_found=${response.hints_by_you[0].is_found} (ID: ${response.hints_by_you[0].id})")
            }

            val entitiesToInsert = mutableListOf<HintEntity>()

            response.hints_for_you.mapTo(entitiesToInsert) { detail ->
                mapHintDetailToEntity(detail, "for_you")
            }
            response.hints_by_you.mapTo(entitiesToInsert) { detail ->
                mapHintDetailToEntity(detail, "by_you")
            }

            if (entitiesToInsert.isNotEmpty()) {
                Log.d("HintToggleDebug", "Repo: Inserting ${entitiesToInsert.size} hints. First hint's isFound=${entitiesToInsert[0].isFound} (ID: ${entitiesToInsert[0].hint_db_id})")
                hintDao.insertHints(entitiesToInsert)
                Log.d("HintToggleDebug", "Repo: Insertion complete.")
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
            locationOwnerName = detail.location_owner_name,
            itemOwnerId = detail.item_owner_id,
            locationOwnerId = detail.location_owner_id,
            itemName = detail.item_name,
            locationName = detail.location_name,
            isFound = detail.is_found,
            timestamp = detail.timestamp,
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