package com.jones.aptracker.network

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface HintDao {

    @Query("SELECT * FROM hints WHERE roomDbId = :roomId ORDER BY timestamp DESC")
    fun getAllHintsForRoom(roomId: Int): Flow<List<HintEntity>>

    @Query("SELECT * FROM hints ORDER BY timestamp DESC")
    fun getAllGlobalHints(): Flow<List<HintEntity>>

    @Query("SELECT MAX(timestamp) FROM hints")
    suspend fun getLatestGlobalTimestamp(): String?

    @Query("SELECT MAX(timestamp) FROM hints WHERE roomDbId = :roomId")
    suspend fun getLatestTimestampForRoom(roomId: Int): String?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertHints(hints: List<HintEntity>)

    @Query("DELETE FROM hints")
    suspend fun deleteAllHints()

    @Query("SELECT COUNT(*) FROM hints WHERE roomDbId = :roomId AND isFound = 1")
    suspend fun countFoundHints(roomId: Int): Int

    @Query("SELECT COUNT(*) FROM hints WHERE isFound = 1")
    suspend fun countGlobalFoundHints(): Int

    @Query("UPDATE hints SET roomDbId = :newId WHERE roomDbId = :oldId")
    suspend fun updateRoomIdForHints(oldId: Int, newId: Int)
}