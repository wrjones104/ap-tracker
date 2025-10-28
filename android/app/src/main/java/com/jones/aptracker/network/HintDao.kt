package com.jones.aptracker.network

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface HintDao {

    // Get hints for a specific room, categorized
    @Query("SELECT * FROM hints WHERE roomDbId = :roomId AND hintType = :type AND (isFound = 0 OR :includeFound = 1) ORDER BY timestamp DESC")
    fun getHintsForRoom(roomId: Int, type: String, includeFound: Int): Flow<List<HintEntity>>

    // Get all hints, categorized
    @Query("SELECT * FROM hints WHERE hintType = :type AND (isFound = 0 OR :includeFound = 1) ORDER BY timestamp DESC")
    fun getGlobalHints(type: String, includeFound: Int): Flow<List<HintEntity>>

    // Get the latest timestamp for sync (global)
    @Query("SELECT MAX(timestamp) FROM hints")
    suspend fun getLatestGlobalTimestamp(): String?

    // Get the latest timestamp for sync (per-room)
    @Query("SELECT MAX(timestamp) FROM hints WHERE roomDbId = :roomId")
    suspend fun getLatestTimestampForRoom(roomId: Int): String?

    // Insert new hints, replacing duplicates based on the backend ID
    // --- THIS IS THE FIX ---
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertHints(hints: List<HintEntity>)
    // --- END OF FIX ---

    // --- Add a function to clear hints if needed (e.g., for full sync) ---
    // @Query("DELETE FROM hints")
    // suspend fun clearAllHints()
}