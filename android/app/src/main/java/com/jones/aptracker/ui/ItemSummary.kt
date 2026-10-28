package com.jones.aptracker.ui

import com.jones.aptracker.network.SlotItemSummaryRow

/** One line of a slot's item summary (#465): an item name and how many the slot has received. */
data class ItemSummaryEntry(
    val itemName: String,
    val count: Int,
    /** Id of the latest copy. Ids follow the order items reached the server. */
    val latestId: Long,
    val latestTimestamp: String,
    val itemFlags: Int
)

enum class ItemSummarySort(val label: String) {
    RECENT("Recent"),
    COUNT("Count"),
    NAME("A–Z")
}

/**
 * The server deletes item history after its retention window (90 days) but keeps each slot's
 * per-item totals, and every row carries that total as of when it was sent. So the cached rows
 * alone undercount a long game; the latest copy's total does not. The larger of the two wins,
 * which also covers rows cached before the server sent totals.
 */
fun toItemSummary(rows: List<SlotItemSummaryRow>): List<ItemSummaryEntry> = rows.map {
    ItemSummaryEntry(
        itemName = it.itemName,
        count = maxOf(it.cachedCount, it.latestReceivedCount ?: 0),
        latestId = it.latestId,
        latestTimestamp = it.latestTimestamp,
        itemFlags = it.itemFlags
    )
}

/**
 * Recent sorts by id, not timestamp: a backfill can stamp a whole batch with one time, while ids
 * keep the order the items arrived in.
 */
fun sortItemSummary(entries: List<ItemSummaryEntry>, sort: ItemSummarySort): List<ItemSummaryEntry> {
    val byName = compareBy<ItemSummaryEntry, String>(String.CASE_INSENSITIVE_ORDER) { it.itemName }
        .thenBy { it.itemName }
    return when (sort) {
        ItemSummarySort.RECENT -> entries.sortedByDescending { it.latestId }
        ItemSummarySort.COUNT -> entries.sortedWith(compareByDescending<ItemSummaryEntry> { it.count }.then(byName))
        ItemSummarySort.NAME -> entries.sortedWith(byName)
    }
}
