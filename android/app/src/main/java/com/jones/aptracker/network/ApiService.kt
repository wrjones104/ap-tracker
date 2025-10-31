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
    suspend fun registerDevice(@Body request: DeviceRegisterRequest): Response<Unit>

    @POST("auth/callback")
    suspend fun exchangeCodeForToken(@Body request: AuthRequest): AuthResponse

    @GET("users/me")
    suspend fun getUserProfile(): UserProfile

    @PUT("users/me/preferences")
    suspend fun updateUserPreferences(@Body request: UpdateGlobalPrefsRequest): Response<Unit>

    @PUT("rooms/{id}/slots/{slot_id}/preferences")
    suspend fun updateSlotPreferences(
        @Path("id") roomId: Int,
        @Path("slot_id") slotId: Int,
        @Body request: UpdateSlotPrefsRequest
    ): Response<Unit>

    @GET("users/me/tracked-slots")
    suspend fun getUserTrackedSlots(): List<RoomWithTrackedSlots>

    @GET("history/hints")
    suspend fun getGlobalHintHistory(
        @Query("since") since: String?,
        @Query("include_found") includeFound: Boolean
    ): HintHistoryResponse

    @GET("rooms/{id}/history/hints")
    suspend fun getRoomHintHistory(
        @Path("id") roomId: Int,
        @Query("since") since: String?,
        @Query("include_found") includeFound: Boolean
    ): HintHistoryResponse

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
    val room_url: String,
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
    val is_tracked: Boolean,
    val notify_progression: Boolean?,
    val notify_useful: Boolean?,
    val notify_hints: Boolean?
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
    val fcm_token: String
)

data class AuthRequest(
    val code: String,
    val redirect_uri: String,
    val code_verifier: String
)

data class AuthResponse(val token: String)

data class UserProfile(
    val discord_id: String,
    val discord_username: String,
    val avatar_url: String?,
    val notify_progression_default: Boolean,
    val notify_useful_default: Boolean,
    val notify_hints_default: Boolean
)

data class UpdateGlobalPrefsRequest(
    val notify_progression: Boolean? = null,
    val notify_useful: Boolean? = null,
    val notify_hints: Boolean? = null
)

data class UpdateSlotPrefsRequest(
    val notify_progression: Boolean?,
    val notify_useful: Boolean?,
    val notify_hints: Boolean?
)

data class RoomWithTrackedSlots(
    val room_db_id: Int,
    val room_alias: String,
    val icon_name: String,
    val tracked_slots: List<TrackedSlotDetail>
)

data class TrackedSlotDetail(
    val slot_id: Int,
    val player_name: String,
    val notify_progression: Boolean?,
    val notify_useful: Boolean?,
    val notify_hints: Boolean?
)

data class HintHistoryResponse(
    val hints_for_you: List<HintDetail>,
    val hints_by_you: List<HintDetail>
)

data class HintDetail(
    val id: Int,
    val room_db_id: Int,
    val room_alias: String,
    val item_owner_id: Int,
    val item_owner_name: String,
    val location_owner_id: Int,
    val location_owner_name: String,
    val item_name: String,
    val location_name: String,
    val is_found: Boolean,
    val timestamp: String
)