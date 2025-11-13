package com.jones.aptracker.network

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import kotlinx.coroutines.flow.Flow

@Dao
interface RoomDao {

    @Query("SELECT * FROM rooms ORDER BY alias ASC")
    fun getAllRooms(): Flow<List<RoomEntity>>

    @Query("DELETE FROM rooms")
    suspend fun clearAllRooms()

    @Query("DELETE FROM rooms WHERE id NOT IN (:validIds)")
    suspend fun deleteObsoleteRooms(validIds: List<Int>)
    // ---------------------------------------------

    @Transaction
    suspend fun syncRooms(rooms: List<RoomEntity>) {
        if (rooms.isEmpty()) {
            clearAllRooms()
        } else {
            insertOrUpdateRooms(rooms)

            val validIds = rooms.map { it.id }

            deleteObsoleteRooms(validIds)
        }
    }

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertOrUpdateRooms(rooms: List<RoomEntity>)
}