package com.jones.aptracker.network

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import kotlinx.coroutines.flow.Flow

/** Ids per UPDATE in [HistoryDao.applyFilterFlags], under SQLite's 999 bound-value limit on API 26. */
internal const val FILTER_FLAG_CHUNK = 500

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

    // Only the flagged rows: on a large cache most rows have neither flag to clear.
    @Query("UPDATE history_items SET isIgnored = 0, isWhitelisted = 0 WHERE isIgnored = 1 OR isWhitelisted = 1")
    suspend fun clearFilterFlags()

    @Query("UPDATE history_items SET isIgnored = 1 WHERE id IN (:ids)")
    suspend fun markIgnored(ids: List<Long>)

    @Query("UPDATE history_items SET isWhitelisted = 1 WHERE id IN (:ids)")
    suspend fun markWhitelisted(ids: List<Long>)

    /**
     * Re-flags every cached item from the server's current answer (#464): clears both flags, then
     * sets them for the ids given, in one transaction so no screen reads a half-applied state.
     * Chunked because SQLite on API 26 binds at most 999 values per statement.
     */
    @Transaction
    suspend fun applyFilterFlags(ignoredIds: List<Long>, whitelistedIds: List<Long>) {
        clearFilterFlags()
        ignoredIds.chunked(FILTER_FLAG_CHUNK).forEach { markIgnored(it) }
        whitelistedIds.chunked(FILTER_FLAG_CHUNK).forEach { markWhitelisted(it) }
    }

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

    /**
     * One row per item name a slot has received, for the item summary (#465). A Flow, so the
     * summary updates as syncs and pushes store new items.
     *
     * MAX(id) is the only min/max aggregate, so SQLite fills the bare columns (timestamp,
     * itemFlags, receivedCount) from the latest copy of each item.
     */
    @Query("""
        SELECT itemName, COUNT(*) AS cachedCount, MAX(id) AS latestId,
               timestamp AS latestTimestamp, itemFlags, receivedCount AS latestReceivedCount
        FROM history_items
        WHERE roomId = :roomId AND slot_id = :slotId
        GROUP BY itemName
    """)
    fun observeItemSummaryForSlot(roomId: Int, slotId: Int): Flow<List<SlotItemSummaryRow>>
}

/** Aggregated row returned by [HistoryDao.getItemCountsForRoom]. */
data class RoomItemCount(
    val slotId: Int?,
    val playerName: String,
    val playerAlias: String?,
    val itemName: String,
    val itemCount: Int
)

/** Aggregated row returned by [HistoryDao.observeItemSummaryForSlot]. */
data class SlotItemSummaryRow(
    val itemName: String,
    /** Copies cached on this device. Short of the real total when history predates retention. */
    val cachedCount: Int,
    val latestId: Long,
    val latestTimestamp: String,
    val itemFlags: Int,
    /** The server's running total as of the latest copy; null on rows cached before it existed. */
    val latestReceivedCount: Int?
)
