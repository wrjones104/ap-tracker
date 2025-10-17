package com.jones.aptracker.network

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

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
    suspend fun getItemHistory(@Path("id") roomId: Int, @Query("since") since: String?): List<HistoryItem>

    @GET("history/items")
    suspend fun getGlobalItemHistory(@Query("since") since: String?): List<HistoryItem>

    @POST("devices")
    suspend fun registerDevice(@Body request: RegisterDeviceRequest): Response<Unit>
}

data class Room(
    val id: Int,
    val room_id: String,
    val alias: String,
    val host: String?,
    val tracked_slots_count: Int,
    val total_slots_count: Int,
    val icon_name: String
)

data class AddRoomRequest(
    val room_id: String,
    val alias: String,
    val icon_name: String
)

data class UpdateRoomRequest(
    val alias: String,
    val icon_name: String
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

data class HistoryItem(
    val message: String,
    val timestamp: String,
    val tracker_id: String?,
    val slot_id: Int?,
    val icon_name: String?,
    val db_id: Int?
)

data class RegisterDeviceRequest(
    val token: String
)