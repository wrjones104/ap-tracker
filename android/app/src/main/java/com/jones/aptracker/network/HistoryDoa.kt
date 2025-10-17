package com.jones.aptracker.network

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface HistoryDao {

    @Query("SELECT * FROM history_items WHERE roomId = :roomId ORDER BY timestamp DESC")
    fun getHistoryForRoom(roomId: Int): Flow<List<HistoryItemEntity>>

    @Query("SELECT * FROM history_items ORDER BY timestamp DESC")
    fun getGlobalHistory(): Flow<List<HistoryItemEntity>>

    @Query("SELECT MAX(timestamp) FROM history_items WHERE roomId = :roomId")
    suspend fun getLatestTimestampForRoom(roomId: Int): String?

    @Query("SELECT MAX(timestamp) FROM history_items")
    suspend fun getLatestGlobalTimestamp(): String?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertHistoryItems(items: List<HistoryItemEntity>)
}