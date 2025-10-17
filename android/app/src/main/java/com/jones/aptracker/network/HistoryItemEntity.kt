package com.jones.aptracker.network

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "history_items")
data class HistoryItemEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0, // Auto-generated unique ID for each row
    val roomId: Int?,      // Null for global, non-null for room-specific items
    val message: String,
    val timestamp: String, // ISO 8601 format
    val tracker_id: String?,
    val slot_id: Int?,
    val icon_name: String?
)