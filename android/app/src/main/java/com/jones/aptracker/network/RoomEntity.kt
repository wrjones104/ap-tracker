package com.jones.aptracker.network

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "rooms")
data class RoomEntity(
    @PrimaryKey
    val id: Int,
    val room_id: String,
    val alias: String,
    val host: String?,
    val tracked_slots_count: Int,
    val total_slots_count: Int,
    val icon_name: String
)