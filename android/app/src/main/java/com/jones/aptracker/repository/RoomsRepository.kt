package com.jones.aptracker.repository

import com.jones.aptracker.network.ApiService
import com.jones.aptracker.network.RoomDao
import com.jones.aptracker.network.RoomEntity
import kotlinx.coroutines.flow.Flow

class RoomsRepository(
    private val apiService: ApiService,
    private val roomDao: RoomDao
) {

    // This Flow will always emit the latest list of rooms from our local database.
    // The UI will observe this to get its data.
    val allRooms: Flow<List<RoomEntity>> = roomDao.getAllRooms()

    /**
     * Fetches the latest list of rooms from the network and updates the local database.
     * If the network call fails, this function will throw an exception, but our
     * local data will remain untouched.
     */
    suspend fun refreshRooms() {
        val networkRooms = apiService.getRooms()
        val roomEntities = networkRooms.map { networkRoom ->
            RoomEntity(
                id = networkRoom.id,
                room_id = networkRoom.room_id,
                alias = networkRoom.alias,
                host = networkRoom.host,
                tracked_slots_count = networkRoom.tracked_slots_count,
                total_slots_count = networkRoom.total_slots_count,
                icon_name = networkRoom.icon_name // <-- ADD THIS
            )
        }
        roomDao.insertOrUpdateRooms(roomEntities)
    }
}