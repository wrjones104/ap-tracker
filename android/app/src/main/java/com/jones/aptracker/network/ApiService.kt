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

    /**
     * Global preferences are written as a sparse map on purpose: this endpoint has no
     * request data class, unlike [UpdateSlotPrefsRequest] for the slot-level one.
     *
     * The sparseness is load-bearing. Retrofit is configured with `serializeNulls()`
     * (`RetrofitClient.kt`) and the server keys off field *presence*, so a fully populated
     * request object would send an explicit null for every preference the caller did not
     * set and clear each one. Callers send only what changed -- often a single key.
     *
     * Values are Any because preferences are no longer all booleans: finished_definition
     * is a string enum. The server validates each field by name.
     */
    @PUT("users/me/preferences")
    suspend fun updateUserPreferences(@Body request: Map<String, @JvmSuppressWildcards Any>): Response<Unit>

    @PUT("rooms/{id}/slots/{slot_id}/preferences")
    suspend fun updateSlotPreferences(
        @Path("id") roomId: Int,
        @Path("slot_id") slotId: Int,
        @Body request: UpdateSlotPrefsRequest
    ): Response<Unit>

    @GET("users/me/tracked-slots")
    suspend fun getUserTrackedSlots(): List<RoomWithTrackedSlots>

    @PUT("rooms/{id}/slots/{slot_id}/cheese")
    suspend fun updateSlotCheese(
        @Path("id") roomId: Int,
        @Path("slot_id") slotId: Int,
        @Body request: Map<String, @JvmSuppressWildcards Any>
    ): Response<UpdateCheeseSlotResponse>

    @POST("rooms/{id}/cheese/refresh")
    suspend fun refreshRoomCheese(@Path("id") roomId: Int): Response<Unit>

    @PUT("users/me/preferences")
    suspend fun updateCheeseDefaultPing(@Body request: UpdateCheesePingRequest): Response<Unit>

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

    /**
     * Creates several milestone groups on one slot in a single transaction, for the "Apply
     * Templates" sheet. Ticking three templates has to mean three groups or none: looping
     * createThresholdGroup would leave a half-applied slot on the first failure and cost a
     * round trip, a refetch and a widget refresh per template.
     */
    @POST("rooms/{id}/slots/{slot_id}/threshold-groups/bulk")
    suspend fun createThresholdGroupsBulk(
        @Path("id") roomId: Int,
        @Path("slot_id") slotId: Int,
        @Body request: BulkCreateThresholdGroupsRequest
    ): Response<BulkCreateThresholdGroupsResponse>

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

    @GET("milestone-templates")
    suspend fun getMilestoneTemplates(
        @Query("game") game: String? = null
    ): List<MilestoneTemplate>

    @POST("milestone-templates")
    suspend fun createMilestoneTemplate(
        @Body request: CreateMilestoneTemplateRequest
    ): Response<Unit>

    @PUT("milestone-templates/{id}")
    suspend fun updateMilestoneTemplate(
        @Path("id") templateId: Int,
        @Body request: CreateMilestoneTemplateRequest
    ): Response<Unit>

    /**
     * Flips one template's "always add to new slots I play" switch. Separate from the full
     * update so the toggle does not round-trip every item just to change a boolean, and so a
     * stale screen cannot silently revert a template's items while toggling it.
     */
    @PUT("milestone-templates/{id}/auto-apply")
    suspend fun setMilestoneTemplateAutoApply(
        @Path("id") templateId: Int,
        @Body request: SetTemplateAutoApplyRequest
    ): Response<Unit>

    @DELETE("milestone-templates/{id}")
    suspend fun deleteMilestoneTemplate(
        @Path("id") templateId: Int
    ): Response<Unit>

    @GET("rooms/{id}/slots/{slot_id}/items")
    suspend fun getAvailableItems(
        @Path("id") roomId: Int,
        @Path("slot_id") slotId: Int
    ): List<AutocompleteOption>

    @GET("rooms/{id}/datapackage")
    suspend fun getRoomDatapackage(@Path("id") roomId: Int): RoomDatapackage

    /**
     * One game's id -> name tables, addressed by datapackage checksum. The response is
     * immutable for a given checksum, so callers cache it on disk indefinitely.
     */
    @GET("datapackage/checksum/{checksum}")
    suspend fun getChecksumDatapackage(@Path("checksum") checksum: String): GameDatapackage

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

    @GET("api/whats_new")
    suspend fun getWhatsNew(
        @Query("target") target: String = "app"
    ): WhatsNewResponse

    @GET("api/whats_new/latest")
    suspend fun getLatestRelease(
        @Query("version") version: String? = null,
        @Query("target") target: String = "app"
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
    /** Goaled. Keeps its original name because it is also the long-standing wire field. */
    val is_finished: Boolean = false,
    /**
     * Nothing left to send from this world. Null when the server has no check counts
     * for the room at all, which degrades every definition to goal-only.
     */
    val has_all_checks: Boolean? = null,
    val checks_done: Int? = null,
    val total_locations: Int? = null,
    val notify_progression: Boolean? = null,
    val notify_useful: Boolean? = null,
    val notify_hints: Boolean? = null,
    /** "play" | "watch". Null when the slot is not tracked. See [TrackMode]. */
    val track_mode: String? = null,
    /**
     * Cheese Tracker claim state for this slot. Non-null whenever the user is
     * connected to Cheese, which is exactly when the picker should offer the
     * Playing/Watching choice. A room not yet linked to a tracker reports
     * nothing as claimed, so the choice is open rather than hidden.
     */
    val cheese_claim: CheeseClaim? = null
)

/**
 * Whether a tracked slot is claimed on Cheese Tracker ("Playing") or is
 * alerts-only ("Watching"). Watching never writes to Cheese, so it works for
 * shared slots, async hosts, and slots that were auto-released.
 */
object TrackMode {
    const val PLAY = "play"
    const val WATCH = "watch"
}

data class CheeseClaim(
    val is_claimed: Boolean = false,
    val is_mine: Boolean = false,
    /** Display name of the holder, or null if they are anonymous to us. */
    val claimed_by: String? = null,
    /** False when someone else holds the slot: the picker must force Watching. */
    val can_claim: Boolean = true,
    /**
     * False when the room has not synced with Cheese yet, so the fields above are
     * what we would attempt rather than what Cheese reports -- someone else may
     * hold the slot. Defaults true so a payload from an older server reads as
     * before.
     */
    val is_known: Boolean = true
)

data class UpdateSlotsRequest(
    val tracked_slot_ids: List<Int>,
    /** {slot_id: "play"|"watch"}. Omitted by older builds; the server then keeps existing modes. */
    val slot_modes: Map<String, String>? = null
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
    /** Goaled, as it has always meant. */
    val isPlayerFinished: Boolean,
    /** Null when the server has no check counts for the room. */
    val playerHasAllChecks: Boolean? = null,
    val itemFlags: Int,
    val timestamp: String,
    val tracker_id: String?,
    val slot_id: Int?,
    val icon_name: String?,
    val room_db_id: Int?,
    val host: String?,
    val receivedCount: Int? = null,
    val isIgnored: Boolean = false,
    val isWhitelisted: Boolean = false
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
    val finished_definition_default: String = "goal",
    val ui_show_found_hints_default: Boolean = false,
    val ui_show_progression_default: Boolean = true,
    val ui_show_useful_default: Boolean = true,
    val ui_show_filler_default: Boolean = false,
    val ui_show_trap_default: Boolean = false,
    val is_cheese_connected: Boolean = false,
    val cheese_default_ping: String? = null,
    val global_snooze_until: String? = null,
    val is_syncing_cheese: Boolean = false,
    /** Slots the last Cheese sync moved from Playing to Watching. */
    val cheese_last_sync_demoted: Int = 0,
    val cheese_last_sync: String? = null
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
    val suppress_connected: Boolean? = null,
    val finished_definition: String? = null
)

/**
 * Build a slot-preferences request carrying this slot's complete current state.
 *
 * The endpoint is a full-state write, not a patch: Retrofit is configured with
 * `serializeNulls()`, and the server keys off field *presence*, so any field left off
 * the request still arrives as an explicit null and clears that slot's override.
 *
 * Both callers -- the single-toggle path and "copy settings to all slots" -- used to
 * enumerate the fields separately, and "copy to all" silently dropped
 * `suppress_connected`, wiping that override on every target slot (issue #261).
 * Building the request in one place from the slot object is what keeps a newly added
 * preference from reintroducing that bug: add the field here and both paths carry it.
 */
fun TrackedSlotDetail.toPrefsRequest(): UpdateSlotPrefsRequest = UpdateSlotPrefsRequest(
    notify_progression = notify_progression,
    notify_useful = notify_useful,
    notify_filler = notify_filler,
    notify_trap = notify_trap,
    notify_hints = notify_hints,
    notify_hints_remote_items = notify_hints_remote_items,
    combine_notifications = combine_notifications,
    suppress_own_events = suppress_own_events,
    remove_emojis = remove_emojis,
    suppress_self_found = suppress_self_found,
    notify_finished = notify_finished,
    use_condensed_messages = use_condensed_messages,
    suppress_connected = suppress_connected,
    finished_definition = finished_definition
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
    /** Goaled. Keeps its original name because it is also the long-standing wire field. */
    val is_finished: Boolean = false,
    /** Null when the server has no check counts for the room. */
    val has_all_checks: Boolean? = null,
    val checks_done: Int? = null,
    val total_locations: Int? = null,
    val game: String? = null,
    val last_activity: String? = null,
    val item_count: Int = 0,
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
    val suppress_connected: Boolean?,
    /** Per-slot override of the user's finished definition. Null inherits the default. */
    val finished_definition: String? = null,
    /** "play" | "watch". See [TrackMode]. */
    val track_mode: String = TrackMode.PLAY,
    val cheese: CheeseSlotState? = null
)

/**
 * Per-slot Cheese Tracker state. Present only when the user is connected to
 * Cheese Tracker and the room is linked to a CT tracker. Null otherwise, which
 * the UI uses to decide whether to show the Cheese Tracker section at all.
 */
data class CheeseSlotState(
    val game_id: Int?,
    val notes: String = "",
    val progression_status: String? = null,
    val completion_status: String? = null,
    val discord_ping: String? = null,
    val last_checked: String? = null,
    val last_activity: String? = null,
    val is_mine: Boolean = false,
    val global_ping_policy: String? = null
)

/**
 * Whether this slot should read as watched in the UI.
 *
 * Only Watching is ever marked, never Playing: play is the default for every slot
 * and the only mode a user who is not on Cheese Tracker ever has, so a "playing"
 * badge would sit on every row and tell them nothing. Marking the exception is what
 * carries information.
 *
 * Gated on the mode alone. It used to also require the per-slot Cheese state, on the
 * grounds that without a linked tracker a stored "watch" described nothing -- true
 * while the picker refused to offer the choice before a room was linked, and wrong
 * as soon as it did (#314). A slot set to Watching on a room still waiting to sync
 * is a real choice with a real effect: it is what stops the link catch-up claiming
 * it. Only a user connected to Cheese can reach watch mode at all, so gating on the
 * mode cannot put an eye on a row that has no business carrying one.
 *
 * One property rather than the condition repeated per screen -- the rooms list, the
 * slot detail header and the activity feed all have to agree on what "watched" means,
 * and they drifted apart the moment each spelled it out for itself.
 */
val TrackedSlotDetail.isWatched: Boolean
    get() = track_mode == TrackMode.WATCH

data class UpdateCheeseSlotResponse(
    val message: String? = null,
    val cheese: CheeseSlotState? = null
)

data class UpdateCheesePingRequest(
    val cheese_default_ping: String?
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
    val item_flags: Int = 0,
    val isIgnored: Boolean = false,
    val isWhitelisted: Boolean = false
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
    val is_group: Boolean = false,
    /**
     * Server-side count for this requirement, or null when the server could not resolve it (or is
     * older than this field). Item-group requirements have no other source of progress: the client
     * knows a name is a group but not which items belong to it.
     */
    val acquired: Int? = null
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

data class BulkCreateThresholdGroupsRequest(
    val groups: List<CreateThresholdGroupRequest>
)

data class BulkCreateThresholdGroupsResponse(
    /**
     * Deliberately not [ThresholdGroup]: the server answers with id and name only, so typing
     * this as the full group would hand callers an `items` list Gson had left null.
     */
    val created: List<CreatedThresholdGroup> = emptyList(),
    /** Groups the server declined to create, with a machine-readable reason. */
    val skipped: List<SkippedThresholdGroup> = emptyList()
)

data class CreatedThresholdGroup(
    val id: Int,
    val name: String?
)

data class SkippedThresholdGroup(
    val name: String?,
    /** "duplicate_name", "no_valid_items" or "slot_group_limit". */
    val reason: String
)

/** The 400 body when a bulk apply creates nothing: every group was skipped, and this says why. */
data class BulkCreateThresholdGroupsError(
    val error: String? = null,
    val skipped: List<SkippedThresholdGroup> = emptyList()
)

data class MilestoneTemplate(
    val id: Int,
    val name: String,
    val game_name: String,
    val items: List<ThresholdGroupItem>,
    /**
     * "Always add this template to new slots I play for this game." Applied server-side on the
     * first poll that knows a newly played slot's game; never retroactive. Defaults to false so
     * a server older than this field reads as "off" -- and sits last so a defaulted parameter
     * never precedes a required one for a positional construction.
     */
    val auto_apply: Boolean = false
)

data class CreateMilestoneTemplateRequest(
    val name: String,
    val game_name: String,
    val items: List<ThresholdGroupItemRequest>
)

data class SetTemplateAutoApplyRequest(
    val auto_apply: Boolean
)

data class RoomDatapackage(
    val players: Map<String, String> = emptyMap(),
    /** Item name by "<checksum>_<itemId>". */
    val items: Map<String, String> = emptyMap(),
    /** Location name by "<checksum>_<locationId>". */
    val locations: Map<String, String> = emptyMap(),
    val slot_to_checksum: Map<String, String> = emptyMap(),
    /**
     * Checksum of the generic "Archipelago" game, when the room has one. Its ids are
     * valid in every world -- location -1 is Cheat Console and -2 is Server -- so a
     * lookup that misses in a slot's own game falls back here before giving up.
     */
    val generic_checksum: String? = null
)

/** One game's id -> name tables, as served by /datapackage/checksum/{checksum}. */
data class GameDatapackage(
    val checksum: String = "",
    val game: String? = null,
    val items: Map<String, String> = emptyMap(),
    val locations: Map<String, String> = emptyMap()
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