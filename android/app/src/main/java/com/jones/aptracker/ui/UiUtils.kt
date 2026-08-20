package com.jones.aptracker.ui

import com.jones.aptracker.network.Room
import com.jones.aptracker.network.RoomEntity
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

enum class DateFormatPreset(val key: String, val description: String, val pattern: String?) {
    SYSTEM_DEFAULT("SYSTEM_DEFAULT", "System Default", null),
    ISO_LIKE("ISO_LIKE", "ISO", "yyyy-MM-dd HH:mm"),
    US_12H("US_12H", "US", "MM/dd/yyyy h:mm a"),
    EU_24H("EU_24H", "Europe", "dd/MM/yyyy HH:mm"),
    DE_24H("DE_24H", "Germany", "dd.MM.yyyy HH:mm"),
    FRIENDLY_12H("FRIENDLY_12H", "Friendly", "MMM d, yyyy h:mm a");

    /**
     * A formatted example of this preset, e.g. "Jun 8, 2026 12:05 PM".
     *
     * Exposed separately from [label] so a caller can show the name and the example on
     * their own lines. Combined, they are too long to sit in a settings row's value column.
     */
    val sample: String
        get() {
            val at = java.time.ZonedDateTime.of(2026, 6, 8, 12, 5, 0, 0, java.time.ZoneId.systemDefault())
            return at.format(getFormatter(isDetail = true))
        }

    /** Name plus example, for the picker, where seeing the format is the point. */
    val label: String
        get() = if (this == SYSTEM_DEFAULT) description else "$description ($sample)"

    fun getFormatter(isDetail: Boolean = false): DateTimeFormatter {
        return if (pattern != null) {
            DateTimeFormatter.ofPattern(pattern).withZone(ZoneId.systemDefault())
        } else {
            val style = if (isDetail) FormatStyle.MEDIUM else FormatStyle.SHORT
            DateTimeFormatter.ofLocalizedDateTime(style).withZone(ZoneId.systemDefault())
        }
    }

    companion object {
        fun fromKey(key: String?): DateFormatPreset {
            return values().find { it.key == key } ?: SYSTEM_DEFAULT
        }
    }
}


fun getDisplayName(originalName: String?, alias: String?, useCondensed: Boolean): String {
    val safeOriginal = originalName ?: "Unknown"
    if (alias.isNullOrBlank()) return safeOriginal

    return if (useCondensed) {
        alias
    } else {
        "$alias ($safeOriginal)"
    }
}

object RoomMapper {
    fun toDomain(entity: RoomEntity): Room {
        return Room(
            id = entity.id,
            room_id = entity.room_id,
            alias = entity.alias,
            host = entity.host,
            tracked_slots_count = entity.tracked_slots_count,
            total_slots_count = entity.total_slots_count,
            icon_name = entity.icon_name,
            sort_order = entity.sort_order,
            is_archived = entity.is_archived,
            is_suspended = entity.is_suspended,
            status = entity.status,
            web_url = entity.web_url
        )
    }

    fun toEntity(domain: Room, sortOrder: Int): RoomEntity {
        return RoomEntity(
            id = domain.id,
            room_id = domain.room_id,
            alias = domain.alias,
            host = domain.host,
            tracked_slots_count = domain.tracked_slots_count,
            total_slots_count = domain.total_slots_count,
            icon_name = domain.icon_name,
            sort_order = sortOrder,
            is_archived = domain.is_archived,
            is_suspended = domain.is_suspended,
            status = domain.status,
            web_url = domain.web_url
        )
    }

    fun toEntityList(rooms: List<Room>): List<RoomEntity> {
        return rooms.mapIndexed { index, room ->
            toEntity(room, sortOrder = index)
        }
    }
}