package com.jones.aptracker.network

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "hints")
data class HintEntity(
    @PrimaryKey
    val hint_db_id: Int,
    val roomDbId: Int,
    val roomAlias: String,
    val hintType: String,
    val itemOwnerName: String,
    val itemOwnerId: Int = 0,
    val locationOwnerId: Int = 0,
    val locationOwnerName: String,
    val itemName: String,
    val locationName: String,
    val isFound: Boolean,
    val timestamp: String,
    val itemFlags: Int = 0
)