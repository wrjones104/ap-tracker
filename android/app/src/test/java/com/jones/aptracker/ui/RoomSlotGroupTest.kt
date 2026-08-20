package com.jones.aptracker.ui

import com.jones.aptracker.data.FinishedDefinition
import com.jones.aptracker.data.FinishedResolver
import com.jones.aptracker.network.RoomWithTrackedSlots
import com.jones.aptracker.network.TrackedSlotDetail
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pins the asymmetry between the slots screen's two filters.
 *
 * A room used to be dropped whenever its slot list filtered to empty, for either reason.
 * That meant a room disappeared from the app the moment its last slot finished, which
 * reads as the app losing the room -- a room leaving the list should only ever be a user
 * action. Collapsing the two filters back together is the regression these tests exist to
 * catch.
 */
class RoomSlotGroupTest {

    private fun slot(
        id: Int,
        name: String = "Player $id",
        game: String? = "Some Game",
        goaled: Boolean = false,
        allChecks: Boolean? = false
    ) = TrackedSlotDetail(
        slot_id = id,
        player_name = name,
        player_alias = null,
        is_finished = goaled,
        has_all_checks = allChecks,
        game = game,
        notify_progression = null,
        notify_useful = null,
        notify_filler = null,
        notify_trap = null,
        notify_hints = null,
        notify_hints_remote_items = null,
        notify_finished = null,
        use_condensed_messages = null,
        suppress_connected = null
    )

    private fun room(vararg slots: TrackedSlotDetail) = RoomWithTrackedSlots(
        room_db_id = 1,
        room_id = "abc",
        room_alias = "Test Room",
        icon_name = "default",
        tracked_slots = slots.toList()
    )

    private val goalOnly = FinishedResolver.GOAL_ONLY

    @Test
    fun `room survives when every slot is finished and hidden`() {
        val groups = buildRoomSlotGroups(
            listOf(room(slot(1, goaled = true), slot(2, goaled = true))),
            searchQuery = "",
            showFinished = false,
            finishedResolver = goalOnly
        )

        assertEquals(1, groups.size)
        val group = groups.single()
        assertTrue(group.visibleSlots.isEmpty())
        assertTrue(group.isAllFinished)
        assertEquals(2, group.hiddenFinishedCount)
    }

    @Test
    fun `room is dropped when the search matches nothing`() {
        val groups = buildRoomSlotGroups(
            listOf(room(slot(1, name = "Chroma"), slot(2, name = "Jones"))),
            searchQuery = "nobody",
            showFinished = true,
            finishedResolver = goalOnly
        )

        assertTrue(groups.isEmpty())
    }

    @Test
    fun `counts describe the room, not what is on screen`() {
        // The header has to report the real makeup either way, or it cannot tell the user
        // that hidden slots exist.
        val rooms = listOf(room(slot(1, goaled = true), slot(2), slot(3)))

        val hidden = buildRoomSlotGroups(rooms, "", showFinished = false, goalOnly).single()
        val shown = buildRoomSlotGroups(rooms, "", showFinished = true, goalOnly).single()

        assertEquals(3, hidden.totalCount)
        assertEquals(1, hidden.finishedCount)
        assertEquals(2, hidden.activeCount)
        assertEquals(2, hidden.visibleSlots.size)
        assertEquals(1, hidden.hiddenFinishedCount)

        assertEquals(3, shown.totalCount)
        assertEquals(1, shown.finishedCount)
        assertEquals(2, shown.activeCount)
        assertEquals(3, shown.visibleSlots.size)
        assertEquals(0, shown.hiddenFinishedCount)
    }

    @Test
    fun `showing finished slots means nothing reads as all-finished`() {
        val groups = buildRoomSlotGroups(
            listOf(room(slot(1, goaled = true))),
            searchQuery = "",
            showFinished = true,
            finishedResolver = goalOnly
        )

        assertFalse(groups.single().isAllFinished)
    }

    @Test
    fun `a room with no finished slots is never flagged as finished`() {
        val group = buildRoomSlotGroups(
            listOf(room(slot(1), slot(2))),
            searchQuery = "",
            showFinished = false,
            finishedResolver = goalOnly
        ).single()

        assertFalse(group.isAllFinished)
        assertEquals(0, group.finishedCount)
        assertEquals(2, group.activeCount)
    }

    @Test
    fun `the user's definition decides what counts as finished`() {
        // Goaled but still sending: finished under goal-only, active under "both".
        val rooms = listOf(room(slot(1, goaled = true, allChecks = false)))
        val both = FinishedResolver(FinishedDefinition.BOTH, emptyMap())

        val underGoal = buildRoomSlotGroups(rooms, "", showFinished = false, goalOnly).single()
        val underBoth = buildRoomSlotGroups(rooms, "", showFinished = false, both).single()

        assertTrue(underGoal.isAllFinished)
        assertFalse(underBoth.isAllFinished)
        assertEquals(1, underBoth.activeCount)
    }

    @Test
    fun `search and finished filters compose`() {
        // Search narrows to one slot, which is finished and hidden: the room stays,
        // because it was the finished filter that emptied it, not the search.
        val group = buildRoomSlotGroups(
            listOf(room(slot(1, name = "Chroma", goaled = true), slot(2, name = "Jones"))),
            searchQuery = "Chroma",
            showFinished = false,
            finishedResolver = goalOnly
        ).single()

        assertEquals(1, group.totalCount)
        assertTrue(group.isAllFinished)
    }
}
