package com.jones.aptracker.network

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "history_items",
    indices = [Index(value = ["message", "timestamp", "slot_id"], unique = true)]
)
data class HistoryItemEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val roomId: Int?,
    val message: String,
    val timestamp: String,
    val tracker_id: String?,
    val slot_id: Int?,
    val icon_name: String?
)