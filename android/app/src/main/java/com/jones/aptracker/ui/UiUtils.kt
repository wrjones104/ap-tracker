package com.jones.aptracker.ui

import com.jones.aptracker.network.Room
import com.jones.aptracker.network.RoomEntity
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

enum class DateFormatPreset(val key: String, val label: String, val pattern: String?) {
    SYSTEM_DEFAULT("SYSTEM_DEFAULT", "System Default", null),
    ISO_LIKE("ISO_LIKE", "2026-06-08 12:05", "yyyy-MM-dd HH:mm"),
    US_12H("US_12H", "06/08/2026 12:05 PM", "MM/dd/yyyy h:mm a"),
    EU_24H("EU_24H", "08/06/2026 12:05", "dd/MM/yyyy HH:mm"),
    DE_24H("DE_24H", "08.06.2026 12:05", "dd.MM.yyyy HH:mm"),
    FRIENDLY_12H("FRIENDLY_12H", "Jun 8, 2026 12:05 PM", "MMM d, yyyy h:mm a");

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
            is_archived = entity.is_archived
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
            is_archived = domain.is_archived
        )
    }

    fun toEntityList(rooms: List<Room>): List<RoomEntity> {
        return rooms.mapIndexed { index, room ->
            toEntity(room, sortOrder = index)
        }
    }
}