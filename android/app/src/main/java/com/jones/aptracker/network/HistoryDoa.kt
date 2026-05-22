package com.jones.aptracker.network

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface HistoryDao {

    @Query("SELECT * FROM history_items WHERE roomId = :roomId ORDER BY timestamp DESC")
    suspend fun getHistoryForRoom(roomId: Int): List<HistoryItemEntity>

    @Query("SELECT * FROM history_items WHERE roomId = :roomId ORDER BY timestamp DESC LIMIT :limit OFFSET :offset")
    suspend fun getHistoryForRoomPaged(roomId: Int, limit: Int, offset: Int): List<HistoryItemEntity>

    @Query("SELECT * FROM history_items ORDER BY timestamp DESC")
    suspend fun getGlobalHistory(): List<HistoryItemEntity>
    
    @Query("SELECT * FROM history_items ORDER BY timestamp DESC LIMIT :limit OFFSET :offset")
    suspend fun getGlobalHistoryPaged(limit: Int, offset: Int): List<HistoryItemEntity>

    @Query("SELECT MAX(timestamp) FROM history_items WHERE roomId = :roomId")
    suspend fun getLatestTimestampForRoom(roomId: Int): String?

    @Query("SELECT MAX(timestamp) FROM history_items")
    suspend fun getLatestGlobalTimestamp(): String?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertHistoryItems(items: List<HistoryItemEntity>)

    @Query("DELETE FROM history_items WHERE roomId = :roomId AND slot_id IN (:slotIds)")
    suspend fun deleteHistoryForSlots(roomId: Int, slotIds: Set<Int>)

    @Query("DELETE FROM history_items")
    suspend fun deleteAllHistory()
}