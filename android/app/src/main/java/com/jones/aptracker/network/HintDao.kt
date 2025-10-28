package com.jones.aptracker.network

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface HintDao {

    // --- DELETED ---
    // @Query("SELECT * FROM hints WHERE roomDbId = :roomId AND hintType = :type AND (isFound = 0 OR :includeFound = 1) ORDER BY timestamp DESC")
    // fun getHintsForRoom(roomId: Int, type: String, includeFound: Int): Flow<List<HintEntity>>
    //
    // @Query("SELECT * FROM hints WHERE hintType = :type AND (isFound = 0 OR :includeFound = 1) ORDER BY timestamp DESC")
    // fun getGlobalHints(type: String, includeFound: Int): Flow<List<HintEntity>>
    // --- END DELETED ---

    // --- NEW REPLACEMENT QUERIES ---
    @Query("SELECT * FROM hints WHERE roomDbId = :roomId AND hintType = :type AND isFound = 0 ORDER BY timestamp DESC")
    fun getUnfoundHintsForRoom(roomId: Int, type: String): Flow<List<HintEntity>>

    @Query("SELECT * FROM hints WHERE roomDbId = :roomId AND hintType = :type ORDER BY timestamp DESC")
    fun getAllHintsForRoom(roomId: Int, type: String): Flow<List<HintEntity>>

    @Query("SELECT * FROM hints WHERE hintType = :type AND isFound = 0 ORDER BY timestamp DESC")
    fun getUnfoundGlobalHints(type: String): Flow<List<HintEntity>>

    @Query("SELECT * FROM hints WHERE hintType = :type ORDER BY timestamp DESC")
    fun getAllGlobalHints(type: String): Flow<List<HintEntity>>
    // --- END NEW ---

    // Get the latest timestamp for sync (global)
    @Query("SELECT MAX(timestamp) FROM hints")
    suspend fun getLatestGlobalTimestamp(): String?

    // Get the latest timestamp for sync (per-room)
    @Query("SELECT MAX(timestamp) FROM hints WHERE roomDbId = :roomId")
    suspend fun getLatestTimestampForRoom(roomId: Int): String?

    // Insert new hints, replacing duplicates based on the backend ID
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertHints(hints: List<HintEntity>)

}