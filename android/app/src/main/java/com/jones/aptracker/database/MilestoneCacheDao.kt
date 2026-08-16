package com.jones.aptracker.database

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction

@Dao
interface MilestoneCacheDao {

    @Query("SELECT * FROM cached_tracked_slots")
    suspend fun getAllTrackedSlots(): List<CachedTrackedSlotEntity>

    @Query("SELECT * FROM cached_tracked_slots WHERE roomDbId = :roomDbId")
    suspend fun getTrackedSlotsForRoom(roomDbId: Int): List<CachedTrackedSlotEntity>

    @Query("SELECT * FROM cached_milestone_groups")
    suspend fun getAllMilestoneGroups(): List<CachedMilestoneGroupEntity>

    @Query("SELECT * FROM cached_milestone_groups WHERE roomDbId = :roomDbId")
    suspend fun getMilestoneGroupsForRoom(roomDbId: Int): List<CachedMilestoneGroupEntity>

    /**
     * Newest tracked-slot write, or null if a refresh has never completed. The widget uses this to
     * tell "we have never synced" apart from "this scope genuinely has no milestones", so it can
     * show a loading hint in the first case and the empty state in the second.
     */
    @Query("SELECT MAX(updatedAt) FROM cached_tracked_slots")
    suspend fun getLastTrackedSlotRefresh(): Long?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertTrackedSlots(slots: List<CachedTrackedSlotEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertMilestoneGroups(groups: List<CachedMilestoneGroupEntity>)

    @Query("DELETE FROM cached_tracked_slots")
    suspend fun clearTrackedSlots()

    @Query("DELETE FROM cached_milestone_groups WHERE roomDbId = :roomDbId AND slotId = :slotId")
    suspend fun clearMilestoneGroupsForSlot(roomDbId: Int, slotId: Int)

    @Query("DELETE FROM cached_milestone_groups WHERE roomDbId NOT IN (:roomDbIds)")
    suspend fun deleteMilestoneGroupsForRoomsNotIn(roomDbIds: List<Int>)

    @Transaction
    suspend fun replaceTrackedSlots(slots: List<CachedTrackedSlotEntity>) {
        clearTrackedSlots()
        insertTrackedSlots(slots)
    }

    /**
     * Replaces one slot's groups. Scoped per slot so that a slot whose network fetch failed keeps
     * its previously cached groups instead of being wiped.
     */
    @Transaction
    suspend fun replaceMilestoneGroupsForSlot(
        roomDbId: Int,
        slotId: Int,
        groups: List<CachedMilestoneGroupEntity>
    ) {
        clearMilestoneGroupsForSlot(roomDbId, slotId)
        if (groups.isNotEmpty()) {
            insertMilestoneGroups(groups)
        }
    }
}
