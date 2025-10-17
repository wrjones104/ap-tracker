package com.jones.aptracker.repository

import com.jones.aptracker.network.ApiService
import com.jones.aptracker.network.HistoryDao
import com.jones.aptracker.network.HistoryItemEntity
import kotlinx.coroutines.flow.Flow

class HistoryRepository(
    private val apiService: ApiService,
    private val historyDao: HistoryDao
) {

    fun getHistoryForRoom(roomId: Int): Flow<List<HistoryItemEntity>> {
        return historyDao.getHistoryForRoom(roomId)
    }

    fun getGlobalHistory(): Flow<List<HistoryItemEntity>> {
        return historyDao.getGlobalHistory()
    }

    suspend fun refreshRoomHistory(roomId: Int) {
        val latestTimestamp = historyDao.getLatestTimestampForRoom(roomId)
        val newItems = apiService.getItemHistory(roomId, since = latestTimestamp)

        if (newItems.isNotEmpty()) {
            val entities = newItems.map { item ->
                HistoryItemEntity(
                    roomId = roomId,
                    message = item.message,
                    timestamp = item.timestamp,
                    tracker_id = item.tracker_id,
                    slot_id = item.slot_id,
                    icon_name = item.icon_name
                )
            }
            historyDao.insertHistoryItems(entities)
        }
    }

    suspend fun refreshGlobalHistory() {
        val latestTimestamp = historyDao.getLatestGlobalTimestamp()
        // --- THE FIX IS HERE: Changed to getGlobalItemHistory ---
        val newItems = apiService.getGlobalItemHistory(since = latestTimestamp)

        if (newItems.isNotEmpty()) {
            val entities = newItems.map { item ->
                HistoryItemEntity(
                    roomId = null,
                    message = item.message,
                    timestamp = item.timestamp,
                    tracker_id = item.tracker_id,
                    slot_id = item.slot_id,
                    icon_name = item.icon_name
                )
            }
            historyDao.insertHistoryItems(entities)
        }
    }
}