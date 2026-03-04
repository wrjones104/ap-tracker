// In com.jones.aptracker.repository.RoomsRepository.kt

package com.jones.aptracker.repository

import com.jones.aptracker.network.AddRoomRequest
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

        val localRooms = roomDao.getAllRoomsOneShot()
        val sortOrderMap = localRooms.associate { it.room_id to it.sort_order }

        var nextSortOrder = (localRooms.maxOfOrNull { it.sort_order } ?: 0) + 1

        val roomEntities = networkRooms.map { networkRoom ->
            val currentOrder = sortOrderMap[networkRoom.room_id]
            val finalOrder = currentOrder ?: nextSortOrder++

            RoomEntity(
                id = networkRoom.id,
                room_id = networkRoom.room_id,
                alias = networkRoom.alias,
                host = networkRoom.host,
                tracked_slots_count = networkRoom.tracked_slots_count,
                total_slots_count = networkRoom.total_slots_count,
                icon_name = networkRoom.icon_name,
                sort_order = finalOrder,
                is_archived = networkRoom.is_archived
            )
        }
        roomDao.syncRooms(roomEntities)
    }

    suspend fun updateRoomOrder(rooms: List<RoomEntity>) {
        roomDao.updateRooms(rooms)
    }

    suspend fun addRoom(request: AddRoomRequest) {
        val response = apiService.addRoom(request)
        if (!response.isSuccessful) throw Exception("Failed to add room")
        refreshRooms()
    }

    suspend fun refreshArchivedRooms(): List<com.jones.aptracker.network.Room> {
        return apiService.getRooms(archived = true)
    }
}