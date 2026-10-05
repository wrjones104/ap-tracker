package com.jones.aptracker.ui

import com.jones.aptracker.network.HintEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pins how the History screen files hints, now that the full hint download no longer re-files
 * every hint on each sync (#411).
 *
 * The type stored with a hint is decided once, when it arrives. Trusting it would leave a hint
 * misfiled after the user changes which slots they track, or when another room tracks a slot
 * with the same number. classifyHints derives the type from the live tracked slots instead,
 * by the server's rule.
 */
class HintClassificationTest {

    private fun hint(
        id: Int,
        room: Int,
        itemOwner: Int,
        locationOwner: Int,
        storedType: String = "by_you"
    ) = HintEntity(
        hint_db_id = id,
        roomDbId = room,
        roomAlias = "Room $room",
        hintType = storedType,
        itemOwnerName = "Player $itemOwner",
        itemOwnerAlias = null,
        itemOwnerId = itemOwner,
        locationOwnerId = locationOwner,
        locationOwnerName = "Player $locationOwner",
        locationOwnerAlias = null,
        itemName = "Item $id",
        locationName = "Location $id",
        isFound = false,
        timestamp = "2026-10-02T12:00:00Z"
    )

    @Test
    fun itemOwnerTrackedIsForYou() {
        val result = classifyHints(listOf(hint(1, room = 10, itemOwner = 3, locationOwner = 7)), setOf(10 to 3))
        assertEquals(listOf(1), result.forYou.map { it.hint_db_id })
        assertTrue(result.byYou.isEmpty())
    }

    @Test
    fun onlyLocationOwnerTrackedIsByYou() {
        val result = classifyHints(listOf(hint(1, room = 10, itemOwner = 3, locationOwner = 7)), setOf(10 to 7))
        assertTrue(result.forYou.isEmpty())
        assertEquals(listOf(1), result.byYou.map { it.hint_db_id })
    }

    @Test
    fun bothOwnersTrackedIsForYouOnly() {
        // The server puts such a hint in hints_for_you only; it must not show twice.
        val result = classifyHints(listOf(hint(1, room = 10, itemOwner = 3, locationOwner = 7)), setOf(10 to 3, 10 to 7))
        assertEquals(listOf(1), result.forYou.map { it.hint_db_id })
        assertTrue(result.byYou.isEmpty())
    }

    @Test
    fun hintTouchingNoTrackedSlotIsDropped() {
        // The delta sync sends every hint in a room, including other players' hints.
        val result = classifyHints(listOf(hint(1, room = 10, itemOwner = 3, locationOwner = 7)), setOf(10 to 5))
        assertTrue(result.forYou.isEmpty())
        assertTrue(result.byYou.isEmpty())
    }

    @Test
    fun sameSlotNumberInAnotherRoomDoesNotCount() {
        // Slot 3 is tracked in room 20, not room 10. A bare slot id would call this "for you".
        val result = classifyHints(
            listOf(hint(1, room = 10, itemOwner = 3, locationOwner = 7)),
            setOf(20 to 3, 10 to 7)
        )
        assertTrue(result.forYou.isEmpty())
        assertEquals(listOf(1), result.byYou.map { it.hint_db_id })
    }

    @Test
    fun storedTypeIsOverriddenByLiveTracking() {
        // Stored as "by_you" when the hint arrived; the user has since started tracking slot 3.
        val result = classifyHints(
            listOf(hint(1, room = 10, itemOwner = 3, locationOwner = 7, storedType = "by_you")),
            setOf(10 to 3)
        )
        assertEquals("for_you", result.forYou.single().hintType)
    }

    @Test
    fun orderIsPreserved() {
        val hints = listOf(
            hint(3, room = 10, itemOwner = 3, locationOwner = 7),
            hint(1, room = 10, itemOwner = 3, locationOwner = 8),
            hint(2, room = 10, itemOwner = 4, locationOwner = 3)
        )
        val result = classifyHints(hints, setOf(10 to 3))
        assertEquals(listOf(3, 1), result.forYou.map { it.hint_db_id })
        assertEquals(listOf(2), result.byYou.map { it.hint_db_id })
    }
}
