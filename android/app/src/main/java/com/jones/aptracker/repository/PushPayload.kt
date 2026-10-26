package com.jones.aptracker.repository

import com.google.gson.Gson
import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.jones.aptracker.network.HintEntity
import com.jones.aptracker.network.HistoryItemEntity
import java.time.Instant

/**
 * The items and hint changes a push carries (#416), so the app can store them instead of
 * calling the server back. The server builds them with the code /history/sync uses
 * (`backend/app/services/push_history.py`), so a row stored from a push is the row a sync would
 * have stored.
 *
 * The app may store them only when nothing is missing between what it has and what the push
 * carries ([pushPayloadApplies]); otherwise it syncs as before. Pure: no Android calls, so it is
 * unit tested.
 */
data class PushPayload(
    val roomId: Int,
    val trackerId: String?,
    val host: String?,
    val iconName: String?,
    val roomAlias: String?,
    val trackedSlots: Set<Int>,
    /** slot id to the item id its block starts after; null: the slot's whole history is here. */
    val slots: Map<Int, Long?>,
    /** The hint change the hints start after; null: every hint touching the tracked slots. */
    val hintsAfter: String?,
    val players: Map<Int, PushPlayer>,
    val items: List<PushItem>,
    val hints: List<PushHint>
)

data class PushPlayer(
    val name: String,
    val alias: String?,
    val game: String?,
    val finished: Boolean,
    val hasAllChecks: Boolean?
)

data class PushItem(
    val id: Long,
    val slotId: Int,
    val senderSlotId: Int,
    val itemName: String,
    val locationName: String,
    val flags: Int,
    val receivedCount: Int,
    val filterBits: Int,
    val timestamp: String
)

data class PushHint(
    val id: Int,
    val itemOwnerId: Int,
    val locationOwnerId: Int,
    val itemName: String,
    val locationName: String,
    val isFound: Boolean,
    val flags: Int,
    val filterBits: Int,
    val timestamp: String,
    val updatedAt: String
)

private const val PAYLOAD_VERSION = 2
private const val FILTER_IGNORED = 1
private const val FILTER_WHITELISTED = 2

/** The payload in a push's `history` field, or null when absent, malformed or a version this app does not know. */
fun parsePushPayload(json: String?): PushPayload? {
    if (json.isNullOrBlank()) return null
    return try {
        val root = Gson().fromJson(json, JsonObject::class.java) ?: return null
        if (root.intOrNull("v") != PAYLOAD_VERSION) return null
        PushPayload(
            roomId = root.get("room").asInt,
            trackerId = root.stringOrNull("tracker"),
            host = root.stringOrNull("host"),
            iconName = root.stringOrNull("icon"),
            roomAlias = root.stringOrNull("alias"),
            trackedSlots = root.getAsJsonArray("tracked").map { it.asInt }.toSet(),
            slots = root.getAsJsonArray("slots").associate { block ->
                val pair = block.asJsonArray
                pair[0].asInt to pair[1].longOrNull()
            },
            hintsAfter = root.stringOrNull("hints_after"),
            players = root.getAsJsonObject("players").entrySet().associate { (slot, row) ->
                val r = row.asJsonArray
                slot.toInt() to PushPlayer(
                    name = r[0].asString,
                    alias = r[1].stringOrNull(),
                    game = r[2].stringOrNull(),
                    finished = r[3].asBoolean,
                    hasAllChecks = r[4].booleanOrNull()
                )
            },
            items = root.getAsJsonArray("items").map { element ->
                val r = element.asJsonArray
                PushItem(
                    id = r[0].asLong, slotId = r[1].asInt, senderSlotId = r[2].asInt,
                    itemName = r[3].asString, locationName = r[4].asString, flags = r[5].asInt,
                    receivedCount = r[6].asInt, filterBits = r[7].asInt, timestamp = r[8].asString
                )
            },
            hints = (root.getAsJsonArray("hints") ?: JsonArray()).map { element ->
                val r = element.asJsonArray
                PushHint(
                    id = r[0].asInt, itemOwnerId = r[1].asInt, locationOwnerId = r[2].asInt,
                    itemName = r[3].asString, locationName = r[4].asString, isFound = r[5].asBoolean,
                    flags = r[6].asInt, filterBits = r[7].asInt, timestamp = r[8].asString,
                    updatedAt = r[9].asString
                )
            }
        )
    } catch (e: RuntimeException) {
        // Gson's parse errors and a missing or mistyped field all land here.
        null
    }
}

/**
 * Whether the app can store [payload] without missing anything.
 *
 * - Each item block: the app's newest stored id for the slot ([localMaxIdBySlot]) is at least
 *   where the block starts. A null start means the block holds the slot's whole history.
 * - Hints: the app's hint coverage for the room ([hintCoverage]: the later of its sync cursor
 *   and the newest change a stored push carried) is at least where the hints start. A null
 *   start means every hint touching the tracked slots is here.
 *
 * "At least", not "equal": a sync may already have brought some of these rows, and storing
 * them again replaces them with the same values.
 */
fun pushPayloadApplies(
    payload: PushPayload,
    localMaxIdBySlot: Map<Int, Long?>,
    hintCoverage: Instant?
): Boolean {
    for ((slotId, after) in payload.slots) {
        if (after == null) continue
        val local = localMaxIdBySlot[slotId] ?: return false
        if (local < after) return false
    }
    val hintsAfter = payload.hintsAfter?.let(::parseInstantOrNull) ?: return payload.hintsAfter == null
    return hintCoverage != null && !hintCoverage.isBefore(hintsAfter)
}

/** The later of two hint cursors, either of which may be missing or unreadable. */
fun laterCursor(a: String?, b: String?): Instant? {
    val first = a?.let(::parseInstantOrNull)
    val second = b?.let(::parseInstantOrNull)
    return when {
        first == null -> second
        second == null -> first
        first.isAfter(second) -> first
        else -> second
    }
}

/** The newest hint change [payload] carries, or null when it carries none. */
fun newestHintChange(payload: PushPayload): String? =
    payload.hints.mapNotNull { hint -> parseInstantOrNull(hint.updatedAt)?.let { it to hint.updatedAt } }
        .maxByOrNull { it.first }?.second

/** The items as /history/sync would have had the app store them. */
fun PushPayload.toItemEntities(): List<HistoryItemEntity> = items.map { item ->
    val receiver = players[item.slotId]
    val sender = players[item.senderSlotId]
    HistoryItemEntity(
        id = item.id,
        roomId = roomId,
        timestamp = normalizeTimestamp(item.timestamp),
        playerName = receiver?.name ?: "Player ${item.slotId}",
        playerAlias = receiver?.alias,
        // As the sync derives it: "Unknown" only for a slot missing from the roster, null for
        // a known slot with no game recorded.
        receivingGame = if (receiver != null) receiver.game else "Unknown",
        itemName = item.itemName,
        senderName = sender?.name ?: "Player ${item.senderSlotId}",
        senderAlias = sender?.alias,
        senderGame = if (sender != null) sender.game else "Unknown",
        locationName = item.locationName,
        isPlayerFinished = receiver?.finished ?: false,
        playerHasAllChecks = receiver?.hasAllChecks,
        itemFlags = item.flags,
        tracker_id = trackerId,
        slot_id = item.slotId,
        icon_name = iconName,
        host = host,
        receivedCount = item.receivedCount,
        isIgnored = item.filterBits and FILTER_IGNORED != 0,
        isWhitelisted = item.filterBits and FILTER_WHITELISTED != 0
    )
}

/** The hints as /history/sync would have had the app store them, typed as it types them. */
fun PushPayload.toHintEntities(): List<HintEntity> = hints.map { hint ->
    val owner = players[hint.itemOwnerId]
    val finder = players[hint.locationOwnerId]
    HintEntity(
        hint_db_id = hint.id,
        roomDbId = roomId,
        roomAlias = roomAlias ?: "",
        hintType = if (hint.itemOwnerId in trackedSlots) "for_you" else "by_you",
        itemOwnerName = owner?.name ?: "Player ${hint.itemOwnerId}",
        itemOwnerAlias = owner?.alias,
        itemOwnerId = hint.itemOwnerId,
        locationOwnerId = hint.locationOwnerId,
        locationOwnerName = finder?.name ?: "Player ${hint.locationOwnerId}",
        locationOwnerAlias = finder?.alias,
        itemName = hint.itemName,
        locationName = hint.locationName,
        isFound = hint.isFound,
        timestamp = normalizeTimestamp(hint.timestamp),
        itemFlags = hint.flags,
        isIgnored = hint.filterBits and FILTER_IGNORED != 0,
        isWhitelisted = hint.filterBits and FILTER_WHITELISTED != 0
    )
}

internal fun parseInstantOrNull(value: String): Instant? = try {
    Instant.parse(value)
} catch (e: RuntimeException) {
    null
}

private fun JsonObject.intOrNull(key: String): Int? = get(key)?.takeUnless { it.isJsonNull }?.asInt
private fun JsonObject.stringOrNull(key: String): String? = get(key)?.stringOrNull()
private fun JsonElement.stringOrNull(): String? = takeUnless { it.isJsonNull }?.asString
private fun JsonElement.longOrNull(): Long? = takeUnless { it.isJsonNull }?.asLong
private fun JsonElement.booleanOrNull(): Boolean? = takeUnless { it.isJsonNull }?.asBoolean
