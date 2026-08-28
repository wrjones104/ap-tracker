package com.jones.aptracker.database

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * One game's item and location id -> name tables, stored under its Archipelago
 * datapackage checksum.
 *
 * The checksum is a content hash, so a row can never go stale: a different table means
 * a different checksum and therefore a different row. That is why there is no expiry
 * here and why the key is the checksum rather than a room or slot -- two rooms running
 * the same game share one row, and a room re-rolled with a new apworld simply lands on
 * a new key while the old row stays valid for anyone still on it.
 *
 * Distinct from [CachedDatapackageEntity], which holds *name-only* lists for the
 * autocomplete pickers and carries no ids at all.
 */
@Entity(tableName = "cached_game_datapackages")
data class CachedGameDatapackageEntity(
    @PrimaryKey val checksum: String,
    val game: String? = null,
    /** JSON object of item id (as string) -> item name. */
    val itemsJson: String,
    /** JSON object of location id (as string) -> location name. */
    val locationsJson: String,
    val updatedAt: Long = System.currentTimeMillis()
)
