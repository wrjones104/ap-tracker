package com.jones.aptracker.network

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "hints")
data class HintEntity(
    @PrimaryKey(autoGenerate = true)
    val local_id: Long = 0, // Local DB ID
    val hint_db_id: Int,    // ID from the backend NotifiedHint table
    val roomDbId: Int,
    val roomAlias: String,
    val hintType: String, // "for_you" or "by_you"
    val itemOwnerName: String,
    val locationOwnerName: String,
    val itemName: String,
    val locationName: String,
    val isFound: Boolean,
    val timestamp: String // ISO 8601 timestamp string
)