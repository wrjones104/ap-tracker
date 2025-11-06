package com.jones.aptracker.network

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "history_items",
    indices = [Index(value = ["roomId", "playerName", "itemName"], unique = false)]
)
data class HistoryItemEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val roomId: Int?,
    val timestamp: String,
    val playerName: String,
    val itemName: String,
    val isPlayerFinished: Boolean,
    val itemFlags: Int,
    val tracker_id: String?,
    val slot_id: Int?,
    val icon_name: String?,
    val host: String?
)