package com.jones.aptracker.network

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface RoomDao {

    @Query("SELECT * FROM rooms ORDER BY sort_order ASC")
    fun getAllRooms(): Flow<List<RoomEntity>>

    @Query("SELECT * FROM rooms")
    suspend fun getAllRoomsOneShot(): List<RoomEntity>

    @Query("DELETE FROM rooms")
    suspend fun clearAllRooms(): Unit

    @Query("DELETE FROM rooms WHERE id NOT IN (:validIds)")
    suspend fun deleteObsoleteRooms(validIds: List<Int>): Unit

    @Query("SELECT * FROM rooms WHERE room_id = :uuid LIMIT 1")
    suspend fun getRoomByUuid(uuid: String): RoomEntity?

    @Query("DELETE FROM rooms WHERE id = :id")
    suspend fun deleteRoomById(id: Int): Unit

    @Update
    suspend fun updateRooms(rooms: List<RoomEntity>): Unit

    @Transaction
    suspend fun syncRooms(rooms: List<RoomEntity>): Unit {
        if (rooms.isEmpty()) {
            clearAllRooms()
        } else {
            insertOrUpdateRooms(rooms)
            val validIds = rooms.map { it.id }
            deleteObsoleteRooms(validIds)
        }
    }

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertOrUpdateRooms(rooms: List<RoomEntity>): Unit
}