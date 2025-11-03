package com.jones.aptracker.network

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface HintDao {

    @Query("SELECT * FROM hints WHERE roomDbId = :roomId AND hintType = :type AND isFound = 0 ORDER BY timestamp DESC")
    suspend fun getUnfoundHintsForRoom(roomId: Int, type: String): List<HintEntity>

    @Query("SELECT * FROM hints WHERE roomDbId = :roomId AND hintType = :type ORDER BY timestamp DESC")
    suspend fun getAllHintsForRoom(roomId: Int, type: String): List<HintEntity>

    @Query("SELECT * FROM hints WHERE hintType = :type AND isFound = 0 ORDER BY timestamp DESC")
    suspend fun getUnfoundGlobalHints(type: String): List<HintEntity>

    @Query("SELECT * FROM hints WHERE hintType = :type ORDER BY timestamp DESC")
    suspend fun getAllGlobalHints(type: String): List<HintEntity>

    @Query("SELECT MAX(timestamp) FROM hints")
    suspend fun getLatestGlobalTimestamp(): String?

    @Query("SELECT MAX(timestamp) FROM hints WHERE roomDbId = :roomId")
    suspend fun getLatestTimestampForRoom(roomId: Int): String?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertHints(hints: List<HintEntity>)
}