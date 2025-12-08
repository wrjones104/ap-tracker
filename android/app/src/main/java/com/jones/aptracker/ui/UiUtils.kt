package com.jones.aptracker.ui

import com.jones.aptracker.network.Room
import com.jones.aptracker.network.RoomEntity

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