package com.jones.aptracker.ui

import com.jones.aptracker.network.SlotItemSummaryRow
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Pins the item summary's counts and sort orders (#465).
 *
 * The count matters most: the server deletes item history after 90 days but keeps per-item
 * totals, so counting cached rows alone would undercount any long game.
 */
class ItemSummaryTest {

    private fun row(
        name: String,
        cached: Int,
        latestId: Long,
        serverTotal: Int? = cached,
        flags: Int = 0
    ) = SlotItemSummaryRow(
        itemName = name,
        cachedCount = cached,
        latestId = latestId,
        latestTimestamp = "2026-10-28T12:00:00Z",
        itemFlags = flags,
        latestReceivedCount = serverTotal
    )

    @Test
    fun `server total wins when history has been purged`() {
        val summary = toItemSummary(listOf(row("Bomb", cached = 3, latestId = 10, serverTotal = 8)))
        assertEquals(8, summary.single().count)
    }

    @Test
    fun `cached count wins when the server total is missing or behind`() {
        val summary = toItemSummary(
            listOf(
                row("Bomb", cached = 3, latestId = 10, serverTotal = null),
                row("Arrow", cached = 4, latestId = 11, serverTotal = 0)
            )
        )
        assertEquals(listOf(3, 4), summary.map { it.count })
    }

    @Test
    fun `flags come through for colouring`() {
        val summary = toItemSummary(listOf(row("Hookshot", cached = 1, latestId = 1, flags = 1)))
        assertEquals(1, summary.single().itemFlags)
    }

    private val entries = toItemSummary(
        listOf(
            row("bomb", cached = 8, latestId = 30),
            row("Ice Rod", cached = 1, latestId = 10),
            row("Progressive Sword", cached = 2, latestId = 20),
            row("Arrow", cached = 2, latestId = 5)
        )
    )

    @Test
    fun `recent puts the item received last first`() {
        assertEquals(
            listOf("bomb", "Progressive Sword", "Ice Rod", "Arrow"),
            sortItemSummary(entries, ItemSummarySort.RECENT).map { it.itemName }
        )
    }

    @Test
    fun `count sorts most first and breaks ties by name`() {
        assertEquals(
            listOf("bomb", "Arrow", "Progressive Sword", "Ice Rod"),
            sortItemSummary(entries, ItemSummarySort.COUNT).map { it.itemName }
        )
    }

    @Test
    fun `name sort ignores case`() {
        assertEquals(
            listOf("Arrow", "bomb", "Ice Rod", "Progressive Sword"),
            sortItemSummary(entries, ItemSummarySort.NAME).map { it.itemName }
        )
    }

    @Test
    fun `search matches part of a name and ignores case`() {
        val entries = toItemSummary(
            listOf(row("Small Key", 1, 1), row("Big Key", 1, 2), row("Bomb", 1, 3))
        )
        assertEquals(listOf("Small Key", "Big Key"), filterItemSummary(entries, "  KEY ").map { it.itemName })
        assertEquals(entries, filterItemSummary(entries, " "))
        assertEquals(emptyList<ItemSummaryEntry>(), filterItemSummary(entries, "Hookshot"))
    }
}
