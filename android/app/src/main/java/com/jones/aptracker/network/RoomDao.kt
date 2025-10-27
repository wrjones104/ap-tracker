
package com.jones.aptracker.network

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import kotlinx.coroutines.flow.Flow

@Dao
interface RoomDao {

    /**
     * Gets all rooms from the database, ordered by their alias.
     * This function returns a Flow, which means it will automatically
     * emit a new list of rooms whenever the data in the table changes.
     * The UI will observe this flow and update itself reactively.
     */
    @Query("SELECT * FROM rooms ORDER BY alias ASC")
    fun getAllRooms(): Flow<List<RoomEntity>>

    @Query("DELETE FROM rooms")
    suspend fun clearAllRooms()

    @Transaction
    suspend fun syncRooms(rooms: List<RoomEntity>) {
        // 1. Delete all rooms currently in the table
        clearAllRooms()
        // 2. Insert the fresh list from the network
        insertOrUpdateRooms(rooms)
    }

    /**
     * Inserts a list of rooms into the database.
     * If a room with the same primary key (id) already exists, it will be replaced.
     * This is perfect for our use case of fetching fresh data from the network
     * and updating our local cache.
     * 'suspend' means this function must be called from a coroutine.
     */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertOrUpdateRooms(rooms: List<RoomEntity>)
}