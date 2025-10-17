package com.jones.aptracker.network

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path

interface ApiService {
    @GET("rooms")
    suspend fun getRooms(): List<Room>

    @POST("rooms")
    suspend fun addRoom(@Body request: AddRoomRequest): Response<Unit>

    @DELETE("rooms/{id}")
    suspend fun deleteRoom(@Path("id") roomId: Int): Response<Unit>

    @PUT("rooms/{id}")
    suspend fun updateRoom(@Path("id") roomId: Int, @Body request: UpdateRoomRequest): Response<Unit>

    @GET("rooms/{id}/players")
    suspend fun getPlayersInRoom(@Path("id") roomId: Int): List<Player>

    @PUT("rooms/{id}/slots")
    suspend fun updateTrackedSlots(@Path("id") roomId: Int, @Body request: UpdateSlotsRequest): Response<Unit>

    @GET("rooms/{id}/history/items")
    suspend fun getItemHistory(@Path("id") roomId: Int): List<HistoryItem>

    // This endpoint was removed from the backend, so we remove it from the app
    // @GET("rooms/{id}/history/hint")
    // suspend fun getHintHistory(@Path("id") roomId: Int): List<HistoryItem>

    @POST("devices")
    suspend fun registerDevice(@Body request: RegisterDeviceRequest): Response<Unit>
}

data class Room(
    val id: Int,
    val room_id: String,
    val alias: String,
    // Making host nullable makes the app more resilient to API errors
    val host: String?,
    val tracked_slots_count: Int,
    val total_slots_count: Int
)

data class AddRoomRequest(
    val room_id: String,
    val alias: String
)

data class UpdateRoomRequest(
    val alias: String
)

data class Player(
    val slot_id: Int,
    val name: String?,
    val game: String?,
    val is_tracked: Boolean
)

data class UpdateSlotsRequest(
    val tracked_slot_ids: List<Int>
)

// The backend now provides a timestamp again
data class HistoryItem(
    val message: String,
    val timestamp: String
)

data class RegisterDeviceRequest(
    val token: String
)
