package com.jones.aptracker.network

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface HistoryDao {

    // Gets history for a specific room, ordered newest first
    @Query("SELECT * FROM history_items WHERE roomId = :roomId ORDER BY timestamp DESC")
    fun getHistoryForRoom(roomId: Int): Flow<List<HistoryItemEntity>>

    // Gets all history items (for the global view), ordered newest first
    @Query("SELECT * FROM history_items ORDER BY timestamp DESC")
    fun getGlobalHistory(): Flow<List<HistoryItemEntity>>

    // Gets the most recent timestamp for a specific room
    @Query("SELECT MAX(timestamp) FROM history_items WHERE roomId = :roomId")
    suspend fun getLatestTimestampForRoom(roomId: Int): String?

    // Gets the most recent timestamp overall
    @Query("SELECT MAX(timestamp) FROM history_items")
    suspend fun getLatestGlobalTimestamp(): String?

    // Inserts new items. Ignores any conflicts.
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertHistoryItems(items: List<HistoryItemEntity>)
}