package com.jones.aptracker.repository

import com.jones.aptracker.network.ApiService
import com.jones.aptracker.network.RoomDao
import com.jones.aptracker.network.RoomEntity
import kotlinx.coroutines.flow.Flow

class RoomsRepository(
    private val apiService: ApiService,
    private val roomDao: RoomDao
) {

    val allRooms: Flow<List<RoomEntity>> = roomDao.getAllRooms()

    suspend fun refreshRooms() {
        val networkRooms = apiService.getRooms()

        // 1. Fetch current local rooms to see existing sort orders
        val localRooms = roomDao.getAllRoomsOneShot()
        val sortOrderMap = localRooms.associate { it.room_id to it.sort_order }

        // 2. Find the highest sort order currently used (for new rooms)
        var nextSortOrder = (localRooms.maxOfOrNull { it.sort_order } ?: 0) + 1

        val roomEntities = networkRooms.map { networkRoom ->
            // 3. Preserve existing order if known, else append to end
            val currentOrder = sortOrderMap[networkRoom.room_id]
            val finalOrder = if (currentOrder != null) {
                currentOrder
            } else {
                val newOrder = nextSortOrder
                nextSortOrder++
                newOrder
            }

            RoomEntity(
                id = networkRoom.id,
                room_id = networkRoom.room_id,
                alias = networkRoom.alias,
                host = networkRoom.host,
                tracked_slots_count = networkRoom.tracked_slots_count,
                total_slots_count = networkRoom.total_slots_count,
                icon_name = networkRoom.icon_name,
                sort_order = finalOrder
            )
        }
        roomDao.syncRooms(roomEntities)
    }

    // Updates the order of the list in the DB
    suspend fun updateRoomOrder(rooms: List<RoomEntity>) {
        roomDao.updateRooms(rooms)
    }
}