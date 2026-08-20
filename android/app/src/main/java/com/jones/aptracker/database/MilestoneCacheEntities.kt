package com.jones.aptracker.database

import androidx.room.Entity

/**
 * Locally cached tracked-slot roster, written by the sync layer and read by the Milestones widget.
 *
 * The widget used to call `/users/me/tracked-slots` itself on every composition. That response is
 * ~750 KB and took ~2.7s, which meant the widget rendered its "Setup needed" placeholder for
 * several seconds after configuration. Caching the handful of fields the widget actually needs
 * keeps the widget's load path entirely local.
 */
@Entity(tableName = "cached_tracked_slots", primaryKeys = ["roomDbId", "slotId"])
data class CachedTrackedSlotEntity(
    val roomDbId: Int,
    val slotId: Int,
    val roomAlias: String,
    val playerName: String,
    val playerAlias: String?,
    val isArchived: Boolean = false,
    /** Goaled. Cached so the Milestones widget can hide finished slots offline (issue #268). */
    val isFinished: Boolean = false,
    /** Nothing left to send. Null when the server has no check counts for the room. */
    val hasAllChecks: Boolean? = null,
    val updatedAt: Long = System.currentTimeMillis()
)

/**
 * Locally cached milestone (threshold) group definitions, one row per group per tracked slot.
 *
 * `itemsJson` holds the serialized `List<ThresholdGroupItem>` requirement list. These are small
 * (a few items each), so a JSON column avoids a second table and a join for no practical cost.
 */
@Entity(tableName = "cached_milestone_groups", primaryKeys = ["roomDbId", "slotId", "groupId"])
data class CachedMilestoneGroupEntity(
    val roomDbId: Int,
    val slotId: Int,
    val groupId: Int,
    val name: String?,
    val isTriggered: Boolean,
    val itemsJson: String,
    val updatedAt: Long = System.currentTimeMillis()
)
