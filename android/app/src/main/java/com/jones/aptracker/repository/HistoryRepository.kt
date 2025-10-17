package com.jones.aptracker.repository

import android.util.Log
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

    suspend fun refreshHistory() {
        // --- ADDED: Log that the refresh is starting ---
        Log.d("HISTORY_DEBUG", "Starting history refresh...")
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
                    Log.d("HISTORY_DEBUG", "Inserting ${entities.size} new entities into the database.")
                    historyDao.insertHistoryItems(entities)
                }
            }
        } catch (e: Exception) {
            // --- ADDED: Catch errors from the API call itself ---
            Log.e("HISTORY_DEBUG", "!!! FAILED to fetch or parse history from network. Error: ${e.message}", e)
        }
    }
}