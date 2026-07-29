package com.jones.aptracker.database

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "cached_datapackages")
data class CachedDatapackageEntity(
    @PrimaryKey val cacheKey: String,
    val game: String? = null,
    val roomDbId: Int? = null,
    val slotId: Int? = null,
    val itemsJson: String,
    val locationsJson: String,
    val updatedAt: Long = System.currentTimeMillis()
)
