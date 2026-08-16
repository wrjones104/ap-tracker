package com.jones.aptracker.network

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface HistoryDao {

    @Query("SELECT * FROM history_items WHERE roomId = :roomId ORDER BY timestamp DESC")
    suspend fun getHistoryForRoom(roomId: Int): List<HistoryItemEntity>

    @Query("SELECT * FROM history_items WHERE roomId = :roomId ORDER BY timestamp DESC LIMIT :limit OFFSET :offset")
    suspend fun getHistoryForRoomPaged(roomId: Int, limit: Int, offset: Int): List<HistoryItemEntity>

    @Query("SELECT * FROM history_items ORDER BY timestamp DESC")
    suspend fun getGlobalHistory(): List<HistoryItemEntity>
    
    @Query("SELECT * FROM history_items ORDER BY timestamp DESC LIMIT :limit OFFSET :offset")
    suspend fun getGlobalHistoryPaged(limit: Int, offset: Int): List<HistoryItemEntity>

    @Query("SELECT MAX(timestamp) FROM history_items WHERE roomId = :roomId")
    suspend fun getLatestTimestampForRoom(roomId: Int): String?

    @Query("SELECT MAX(timestamp) FROM history_items")
    suspend fun getLatestGlobalTimestamp(): String?

    @Query("SELECT MAX(id) FROM history_items WHERE roomId = :roomId AND slot_id = :slotId")
    suspend fun getMaxIdForSlot(roomId: Int, slotId: Int): Int?

    @Query("SELECT COUNT(*) FROM history_items")
    suspend fun getTotalItemCount(): Int

    @Query("SELECT COUNT(*) FROM history_items WHERE roomId = :roomId")
    suspend fun getItemCountForRoom(roomId: Int): Int

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertHistoryItems(items: List<HistoryItemEntity>)

    @Query("DELETE FROM history_items WHERE roomId = :roomId AND slot_id IN (:slotIds)")
    suspend fun deleteHistoryForSlots(roomId: Int, slotIds: Set<Int>)

    @Query("DELETE FROM history_items WHERE roomId = :roomId AND slot_id = :slotId AND id > :maxValidId")
    suspend fun deleteHistoryForSlotAboveId(roomId: Int, slotId: Int, maxValidId: Long)

    @Query("DELETE FROM history_items")
    suspend fun deleteAllHistory()

    @Query("UPDATE history_items SET roomId = :newId WHERE roomId = :oldId")
    suspend fun updateRoomIdForHistory(oldId: Int, newId: Int)

    /**
     * Per-slot item tallies for a room, aggregated in SQLite instead of loading every row.
     *
     * The Milestones widget only needs counts, and a busy room can hold tens of thousands of
     * history rows. Grouping on the raw itemName (rather than LOWER(itemName)) keeps the
     * case-folding in Kotlin, where `lowercase()` is Unicode-aware and SQLite's ASCII-only LOWER()
     * would disagree on non-ASCII item names.
     */
    @Query("""
        SELECT slot_id AS slotId, playerName, playerAlias, itemName, COUNT(*) AS itemCount
        FROM history_items
        WHERE roomId = :roomId
        GROUP BY slot_id, playerName, playerAlias, itemName
    """)
    suspend fun getItemCountsForRoom(roomId: Int): List<RoomItemCount>
}

/** Aggregated row returned by [HistoryDao.getItemCountsForRoom]. */
data class RoomItemCount(
    val slotId: Int?,
    val playerName: String,
    val playerAlias: String?,
    val itemName: String,
    val itemCount: Int
)
