package com.jones.aptracker.network

import com.google.gson.annotations.SerializedName

/**
 * Basic structure for Archipelago WebSocket packets.
 * AP uses a list of objects for all communication.
 */
data class ApPacket(
    val cmd: String,
    @SerializedName("password") val password: String? = null,
    @SerializedName("game") val game: String? = null,
    @SerializedName("name") val name: String? = null,
    @SerializedName("items_handling") val itemsHandling: Int? = null,
    @SerializedName("tags") val tags: List<String>? = null,
    @SerializedName("uuid") val uuid: String? = null,
    @SerializedName("version") val version: ApVersion? = null,
    @SerializedName("text") val text: String? = null,
    @SerializedName("data") val data: List<ApMessageSegment>? = null,
    @SerializedName("type") val type: String? = null,
    @SerializedName("team") val team: Int? = null,
    @SerializedName("slot") val slot: Int? = null,
    @SerializedName("item") val item: ApNetworkItem? = null,
    // RoomInfo: game name -> datapackage checksum for every game in the room.
    @SerializedName("datapackage_checksums") val datapackageChecksums: Map<String, String>? = null,
    // Connected: every player in the multiworld, across all teams.
    @SerializedName("players") val players: List<ApNetworkPlayer>? = null,
    // Connected: slot number -> which game that slot plays.
    @SerializedName("slot_info") val slotInfo: Map<String, ApNetworkSlot>? = null
)

/**
 * A player as the server describes them. [alias] is the name in current time and
 * [name] the one baked in at generation, so alias wins when it is set.
 */
data class ApNetworkPlayer(
    @SerializedName("team") val team: Int = 0,
    @SerializedName("slot") val slot: Int = 0,
    @SerializedName("alias") val alias: String? = null,
    @SerializedName("name") val name: String? = null
)

/**
 * Static information about a slot. [game] is the lookup key that ties a slot to the
 * datapackage its item and location ids belong to -- ids are only unique within one
 * game, so resolving a PrintJSON id without first checking the slot's game is wrong.
 */
data class ApNetworkSlot(
    @SerializedName("name") val name: String? = null,
    @SerializedName("game") val game: String? = null,
    @SerializedName("type") val type: Int = 0,
    @SerializedName("group_members") val groupMembers: List<Int>? = null
)

data class ApNetworkItem(
    val item: Long,
    val location: Long,
    val player: Int,
    val flags: Int
)

data class ApVersion(
    val major: Int,
    val minor: Int,
    val build: Int,
    val `class`: String = "Version"
)

data class ApMessageSegment(
    val text: String,
    val color: String? = null,
    val type: String? = null,
    val player: Int? = null,
    val slot: Int? = null,
    val item: Long? = null,
    val location: Long? = null,
    val flags: Int? = null
)

/**
 * Structured message for internal UI use.
 */
data class ChatMessage(
    val id: String = java.util.UUID.randomUUID().toString(),
    val segments: List<ApMessageSegment>,
    val timestamp: Long = System.currentTimeMillis(),
    val type: String? = null, // e.g., "Chat", "Hint", "Join", etc.
    val slot: Int? = null
)

enum class ConnectionStatus {
    DISCONNECTED,
    CONNECTING,
    CONNECTED,
    ERROR
}

data class AutocompleteOption(
    val name: String,
    @SerializedName("is_group") val isGroup: Boolean = false
)
