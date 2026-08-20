package com.jones.aptracker.network

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "history_items",
    indices = [Index(value = ["roomId", "playerName", "itemName"], unique = false)]
)
data class HistoryItemEntity(
    @PrimaryKey
    val id: Long,
    val roomId: Int?,
    val timestamp: String,
    val playerName: String,
    val playerAlias: String?,
    val receivingGame: String?,
    val itemName: String,
    val senderName: String?,
    val senderAlias: String?,
    val senderGame: String?,
    val locationName: String?,
    /** Goaled. Named for what it has always meant; renaming would churn every call site. */
    val isPlayerFinished: Boolean,
    /**
     * Nothing left to send from this world. Null means the server has no check counts
     * for the room, which degrades every finished definition to goal-only.
     */
    val playerHasAllChecks: Boolean? = null,
    val itemFlags: Int,
    val tracker_id: String?,
    val slot_id: Int?,
    val icon_name: String?,
    val host: String?,
    val receivedCount: Int? = null,
    val isIgnored: Boolean = false,
    val isWhitelisted: Boolean = false
)