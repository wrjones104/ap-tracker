package com.jones.aptracker.network

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.HTTP
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

interface ApiService {
    @GET("rooms")
    suspend fun getRooms(
        @Query("archived") archived: Boolean = false
    ): List<Room>

    @POST("rooms")
    suspend fun addRoom(@Body request: AddRoomRequest): Response<Unit>

    @DELETE("rooms/{id}")
    suspend fun deleteRoom(@Path("id") roomId: Int): Response<Unit>

    @POST("rooms/{id}/revive")
    suspend fun reviveRoom(@Path("id") roomId: Int): Response<Unit>

    @PUT("rooms/{id}")
    suspend fun updateRoom(@Path("id") roomId: Int, @Body request: UpdateRoomRequest): Response<Unit>

    @GET("rooms/{id}/players")
    suspend fun getPlayersInRoom(@Path("id") roomId: Int): List<Player>

    @PUT("rooms/{id}/slots")
    suspend fun updateTrackedSlots(@Path("id") roomId: Int, @Body request: UpdateSlotsRequest): Response<Unit>

    @GET("rooms/{id}/history/items")
    suspend fun getItemHistory(
        @Path("id") roomId: Int,
        @Query("since") since: String? = null,
        @Query("limit") limit: Int? = null,
        @Query("offset") offset: Int? = null
    ): List<HistoryItem>

    @GET("history/items")
    suspend fun getGlobalItemHistory(
        @Query("since") since: String? = null,
        @Query("limit") limit: Int? = null,
        @Query("offset") offset: Int? = null
    ): List<HistoryItem>

    @POST("devices")
    suspend fun registerDevice(@Body request: RegisterDeviceRequest): Response<Unit>

    @POST("auth/callback")
    suspend fun exchangeCodeForToken(@Body request: AuthRequest): AuthResponse

    @GET("users/me")
    suspend fun getUserProfile(): UserProfile

    @PUT("users/me/preferences")
    suspend fun updateUserPreferences(@Body request: Map<String, Boolean>): Response<Unit>

    @PUT("rooms/{id}/slots/{slot_id}/preferences")
    suspend fun updateSlotPreferences(
        @Path("id") roomId: Int,
        @Path("slot_id") slotId: Int,
        @Body request: UpdateSlotPrefsRequest
    ): Response<Unit>

    @GET("users/me/tracked-slots")
    suspend fun getUserTrackedSlots(): List<RoomWithTrackedSlots>

    @GET("rooms/{id}/slots/{slot_id}/threshold-groups")
    suspend fun getThresholdGroups(
        @Path("id") roomId: Int,
        @Path("slot_id") slotId: Int
    ): List<ThresholdGroup>

    @POST("rooms/{id}/slots/{slot_id}/threshold-groups")
    suspend fun createThresholdGroup(
        @Path("id") roomId: Int,
        @Path("slot_id") slotId: Int,
        @Body request: CreateThresholdGroupRequest
    ): Response<Unit>

    @DELETE("rooms/{id}/slots/{slot_id}/threshold-groups/{group_id}")
    suspend fun deleteThresholdGroup(
        @Path("id") roomId: Int,
        @Path("slot_id") slotId: Int,
        @Path("group_id") groupId: Int
    ): Response<Unit>

    @PUT("rooms/{id}/slots/{slot_id}/threshold-groups/{group_id}")
    suspend fun updateThresholdGroup(
        @Path("id") roomId: Int,
        @Path("slot_id") slotId: Int,
        @Path("group_id") groupId: Int,
        @Body request: CreateThresholdGroupRequest
    ): Response<Unit>

    @GET("rooms/{id}/slots/{slot_id}/items")
    suspend fun getAvailableItems(
        @Path("id") roomId: Int,
        @Path("slot_id") slotId: Int
    ): List<AutocompleteOption>

    @GET("rooms/{id}/datapackage")
    suspend fun getRoomDatapackage(@Path("id") roomId: Int): RoomDatapackage

    @GET("rooms/{id}/slots/{slot_id}/locations")
    suspend fun getAvailableLocations(
        @Path("id") roomId: Int,
        @Path("slot_id") slotId: Int
    ): List<AutocompleteOption>

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

    @HTTP(method = "DELETE", path = "devices", hasBody = true)
    suspend fun unregisterDevice(@Body request: RegisterDeviceRequest): Response<Unit>
  
    @DELETE("users/me")
    suspend fun deleteAccount(): Response<Unit>

    @GET("config")
    suspend fun getConfig(): ConfigResponse

    @POST("integrations/cheese/auth")
    suspend fun connectCheeseTracker(@Body request: CheeseAuthRequest): CheeseSyncResponse

    @DELETE("integrations/cheese/auth")
    suspend fun disconnectCheeseTracker(): Response<Unit>

    @POST("integrations/cheese/sync")
    suspend fun syncCheeseTracker(): CheeseSyncResponse

    @POST("auth/logout")
    suspend fun logout(): Response<Unit>

    @POST("auth/guest")
    suspend fun loginAsGuest(): AuthResponse

    @GET("users/me/ignore-list")
    suspend fun getIgnoreList(): List<IgnoreItem>

    @POST("users/me/ignore-list")
    suspend fun addIgnoreItem(@Body request: AddIgnoreItemRequest): AddIgnoreItemResponse

    @DELETE("users/me/ignore-list/{id}")
    suspend fun deleteIgnoreItem(@Path("id") itemId: Int): Response<Unit>

    @GET("games")
    suspend fun getKnownGames(): List<String>

    @GET("games/{gameName}/items")
    suspend fun getGameAvailableItems(
        @Path("gameName") gameName: String
    ): List<AutocompleteOption>

    @GET("games/{gameName}/items/{itemName}/groups")
    suspend fun getItemGroups(
        @Path("gameName") gameName: String,
        @Path("itemName") itemName: String,
        @Query("room_db_id") roomDbId: Int?
    ): List<String>

    @PUT("users/me/ignore-list/{id}")
    suspend fun updateIgnoreItem(
        @Path("id") itemId: Int,
        @Body request: AddIgnoreItemRequest
    ): Response<Unit>

    @GET("users/me/whitelist")
    suspend fun getWhitelist(): List<WhitelistItem>

    @POST("users/me/whitelist")
    suspend fun addWhitelistItem(@Body request: AddWhitelistItemRequest): AddWhitelistItemResponse

    @PUT("users/me/whitelist/{id}")
    suspend fun updateWhitelistItem(
        @Path("id") itemId: Int,
        @Body request: AddWhitelistItemRequest
    ): Response<Unit>

    @DELETE("users/me/whitelist/{id}")
    suspend fun deleteWhitelistItem(@Path("id") itemId: Int): Response<Unit>

    @POST("users/me/snooze")
    suspend fun setGlobalSnooze(@Body request: SnoozeRequest): SnoozeResponse

    @POST("rooms/{id}/slots/{slot_id}/snooze")
    suspend fun setSlotSnooze(
        @Path("id") roomId: Int,
        @Path("slot_id") slotId: Int,
        @Body request: SnoozeRequest
    ): SnoozeResponse

    @POST("users/me/test-notification")
    suspend fun sendTestNotification(): Response<Unit>

    @GET("whats_new")
    suspend fun getWhatsNew(): WhatsNewResponse

    @GET("whats_new/latest")
    suspend fun getLatestRelease(
        @Query("version") version: String? = null
    ): LatestReleaseResponse


    @POST("history/sync")
    suspend fun syncHistory(@Body request: HistorySyncRequest): HistorySyncResponse
}

data class Room(
    val id: Int,
    val room_id: String,
    val alias: String,
    val host: String?,
    val tracked_slots_count: Int,
    val total_slots_count: Int,
    val icon_name: String,
    val sort_order: Int = 0,
    val is_archived: Boolean = false,
    val is_suspended: Boolean = false,
    val status: String = "active",
    val web_url: String? = null
)

data class AddRoomRequest(
    val room_url: String,
    val alias: String,
    val icon_name: String
)

data class UpdateRoomRequest(
    val alias: String? = null,
    val icon_name: String? = null,
    val is_archived: Boolean? = null
)

data class Player(
    val slot_id: Int = 0,
    val name: String? = null,
    val alias: String? = null,
    val game: String? = null,
    val is_tracked: Boolean = false,
    val is_finished: Boolean = false,
    val notify_progression: Boolean? = null,
    val notify_useful: Boolean? = null,
    val notify_hints: Boolean? = null
)

data class UpdateSlotsRequest(
    val tracked_slot_ids: List<Int>
)

data class HistoryItem(
    val id: Long,
    val playerName: String,
    val playerAlias: String?,
    val receivingGame: String?,
    val itemName: String,
    val senderName: String?,
    val senderAlias: String?,
    val senderGame: String?,
    val locationName: String?,
    val isPlayerFinished: Boolean,
    val itemFlags: Int,
    val timestamp: String,
    val tracker_id: String?,
    val slot_id: Int?,
    val icon_name: String?,
    val room_db_id: Int?,
    val host: String?,
    val receivedCount: Int? = null
)

data class RegisterDeviceRequest(
    val fcm_token: String,
    val android_id: String? = null
)

data class AuthRequest(
    val code: String,
    val redirect_uri: String,
    val code_verifier: String
)

data class AuthResponse(val token: String)

data class AuthErrorResponse(
    val error: String,
    val message: String
)

data class UserProfile(
    val discord_id: String?,
    val discord_username: String?,
    val avatar_url: String?,
    val is_guest: Boolean,
    val notify_progression_default: Boolean,
    val notify_useful_default: Boolean,
    val notify_filler_default: Boolean,
    val notify_trap_default: Boolean,
    val notify_hints_default: Boolean,
    val notify_hints_remote_items_default: Boolean,
    val combine_notifications_default: Boolean = false,
    val suppress_own_events_default: Boolean = true,
    val remove_emojis_default: Boolean = false,
    val suppress_self_found_default: Boolean = true,
    val notify_finished_default: Boolean,
    val use_condensed_messages_default: Boolean,
    val suppress_connected_default: Boolean,
    val ui_show_finished_default: Boolean = true,
    val ui_show_found_hints_default: Boolean = false,
    val ui_show_progression_default: Boolean = true,
    val ui_show_useful_default: Boolean = true,
    val ui_show_filler_default: Boolean = false,
    val ui_show_trap_default: Boolean = false,
    val is_cheese_connected: Boolean = false,
    val global_snooze_until: String? = null,
    val is_syncing_cheese: Boolean = false
)

data class UpdateGlobalPrefsRequest(
    val notify_progression: Boolean? = null,
    val notify_useful: Boolean? = null,
    val notify_filler: Boolean? = null,
    val notify_trap: Boolean? = null,
    val notify_hints: Boolean? = null,
    val notify_hints_remote_items: Boolean? = null,
    val combine_notifications: Boolean? = null,
    val suppress_own_events: Boolean? = null,
    val remove_emojis: Boolean? = null,
    val suppress_self_found: Boolean? = null,
    val notify_finished: Boolean? = null,
    val use_condensed_messages: Boolean? = null,
    val ui_show_finished: Boolean? = null,
    val ui_show_found_hints: Boolean? = null,
    val ui_show_filler: Boolean? = null,
    val ui_show_trap: Boolean? = null
)

data class UpdateSlotPrefsRequest(
    val notify_progression: Boolean?,
    val notify_useful: Boolean?,
    val notify_filler: Boolean?,
    val notify_trap: Boolean?,
    val notify_hints: Boolean?,
    val notify_hints_remote_items: Boolean?,
    val combine_notifications: Boolean? = null,
    val suppress_own_events: Boolean? = null,
    val remove_emojis: Boolean? = null,
    val suppress_self_found: Boolean? = null,
    val notify_finished: Boolean? = null,
    val use_condensed_messages: Boolean? = null,
    val suppress_connected: Boolean? = null
)

data class RoomWithTrackedSlots(
    val room_db_id: Int,
    val room_id: String,
    val room_alias: String,
    val icon_name: String,
    val tracked_slots: List<TrackedSlotDetail>,
    val players: List<Player>? = null,
    val is_archived: Boolean = false,
    val host: String? = null
)

data class TrackedSlotDetail(
    val slot_id: Int,
    val player_name: String,
    val player_alias: String?,
    val is_finished: Boolean = false,
    val game: String? = null,
    val last_activity: String? = null,
    val needs_backfill: Boolean = false,
    val notify_progression: Boolean?,
    val notify_useful: Boolean?,
    val notify_filler: Boolean?,
    val notify_trap: Boolean?,
    val notify_hints: Boolean?,
    val notify_hints_remote_items: Boolean?,
    val combine_notifications: Boolean? = null,
    val suppress_own_events: Boolean? = null,
    val remove_emojis: Boolean? = null,
    val suppress_self_found: Boolean? = null,
    val notify_finished: Boolean?,
    val use_condensed_messages: Boolean?,
    val snooze_until: String? = null,
    val suppress_connected: Boolean?
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
    val item_owner_alias: String?,
    val location_owner_id: Int,
    val location_owner_name: String,
    val location_owner_alias: String?,
    val item_name: String,
    val location_name: String,
    val is_found: Boolean,
    val timestamp: String,
    val item_flags: Int = 0
)

data class ConfigResponse(
    val min_app_version: Int
)

data class CheeseAuthRequest(
    val api_key: String
)

data class CheeseSyncResponse(
    val message: String,
    val is_connected: Boolean? = null
)

data class SnoozeRequest(
    val duration_minutes: Int
)

data class SnoozeResponse(
    val message: String,
    val snooze_until: String?
)

data class ThresholdGroup(
    val id: Int,
    val name: String?,
    val is_triggered: Boolean = false,
    val items: List<ThresholdGroupItem>
)

data class ThresholdGroupItem(
    val id: Int? = null,
    val item_name: String,
    val quantity: Int,
    val is_group: Boolean = false
)

data class CreateThresholdGroupRequest(
    val name: String?,
    val items: List<ThresholdGroupItemRequest>
)

data class ThresholdGroupItemRequest(
    val item_name: String,
    val quantity: Int,
    val is_group: Boolean = false
)

data class RoomDatapackage(
    val players: Map<String, String> = emptyMap(),
    val items: Map<String, String> = emptyMap(),
    val item_flags: Map<String, Int> = emptyMap(),
    val locations: Map<String, String> = emptyMap(),
    val slot_to_checksum: Map<String, String> = emptyMap()
)

data class HistorySyncRequest(
    val items: List<SlotSyncWatermark>,
    val hints: List<RoomSyncWatermark>
)

data class SlotSyncWatermark(
    val room_db_id: Int,
    val slot_id: Int,
    val last_timestamp: String? = null,
    val last_id: Int? = null
)

data class RoomSyncWatermark(
    val room_db_id: Int,
    val last_updated: String?
)

data class HistorySyncResponse(
    val new_items: List<HistoryItem>,
    val updated_hints: List<HintDetail>,
    val item_watermarks: Map<String, Any> = emptyMap(),
    val hint_watermarks: Map<String, String?> = emptyMap()
)