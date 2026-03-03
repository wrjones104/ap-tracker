package com.jones.aptracker.network

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface HintDao {

    @Query("SELECT * FROM hints WHERE roomDbId = :roomId AND hintType = :type AND isFound = 0 ORDER BY timestamp DESC")
    fun getUnfoundHintsForRoom(roomId: Int, type: String): Flow<List<HintEntity>>

    @Query("SELECT * FROM hints WHERE roomDbId = :roomId AND hintType = :type ORDER BY timestamp DESC")
    fun getAllHintsForRoom(roomId: Int, type: String): Flow<List<HintEntity>>

    @Query("SELECT * FROM hints WHERE hintType = :type AND isFound = 0 ORDER BY timestamp DESC")
    fun getUnfoundGlobalHints(type: String): Flow<List<HintEntity>>

    @Query("SELECT * FROM hints WHERE hintType = :type ORDER BY timestamp DESC")
    fun getAllGlobalHints(type: String): Flow<List<HintEntity>>

    @Query("SELECT MAX(timestamp) FROM hints")
    suspend fun getLatestGlobalTimestamp(): String?

    @Query("SELECT MAX(timestamp) FROM hints WHERE roomDbId = :roomId")
    suspend fun getLatestTimestampForRoom(roomId: Int): String?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertHints(hints: List<HintEntity>)

    @Query("DELETE FROM hints WHERE roomDbId = :roomId AND (itemOwnerId IN (:slotIds) OR locationOwnerId IN (:slotIds))")
    suspend fun deleteHintsForSlots(roomId: Int, slotIds: Set<Int>)

    @Query("SELECT COUNT(*) FROM hints WHERE roomDbId = :roomId AND isFound = 1")
    suspend fun countFoundHints(roomId: Int): Int

    @Query("SELECT COUNT(*) FROM hints WHERE isFound = 1")
    suspend fun countGlobalFoundHints(): Int
}