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

    @POST("room")
    suspend fun addRoom(@Body request: AddRoomRequest): Response<Unit>

    @DELETE("room/{id}")
    suspend fun deleteRoom(@Path("id") roomId: Int): Response<Unit>

    @PUT("room/{id}")
    suspend fun updateRoom(@Path("id") roomId: Int, @Body request: UpdateRoomRequest): Response<Unit>

    @GET("room/{id}/players")
    suspend fun getPlayersInRoom(@Path("id") roomId: Int): List<Player>

    @PUT("room/{id}/slots")
    suspend fun updateTrackedSlots(@Path("id") roomId: Int, @Body request: UpdateSlotsRequest): Response<Unit>

    @GET("room/{id}/history/items")
    suspend fun getItemHistory(@Path("id") roomId: Int): List<HistoryItem>

    @GET("room/{id}/history/hint")
    suspend fun getHintHistory(@Path("id") roomId: Int): List<HistoryItem>

    @POST("register")
    suspend fun registerDevice(@Body request: RegisterDeviceRequest): Response<Unit>
}

data class Room(
    val id: Int,
    val room_id: String,
    val alias: String,
    val host: String,
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
    // **THE FIX**: Mark name and game as nullable to prevent crashes
    val name: String?,
    val game: String?,
    val is_tracked: Boolean
)

data class UpdateSlotsRequest(
    val tracked_slot_ids: List<Int>
)

data class HistoryItem(
    val message: String,
    val timestamp: String
)

data class RegisterDeviceRequest(
    val token: String
)