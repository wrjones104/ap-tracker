package com.jones.aptracker.data

import com.jones.aptracker.network.RoomWithTrackedSlots
import com.jones.aptracker.network.TrackedSlotDetail
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The Activity screen's saved roster (#468): what a cold start paints from before the server
 * answers. It must come back exactly as saved, and a damaged file must read as "no roster", not
 * crash the screen.
 */
class RosterCacheTest {

    private fun slot(id: Int, alias: String? = null, finished: Boolean = false, allChecks: Boolean? = null) =
        TrackedSlotDetail(
            slot_id = id, player_name = "P$id", player_alias = alias,
            is_finished = finished, has_all_checks = allChecks,
            notify_progression = true, notify_useful = null, notify_filler = false, notify_trap = null,
            notify_hints = null, notify_hints_remote_items = null, notify_finished = true,
            use_condensed_messages = null, suppress_connected = null,
            finished_definition = "goal", track_mode = "watch"
        )

    private val roster = listOf(
        RoomWithTrackedSlots(
            room_db_id = 2, room_id = "uuid-2", room_alias = "BIG", icon_name = "heart",
            tracked_slots = listOf(slot(883, alias = "TS", finished = true, allChecks = false), slot(1757)),
            is_archived = false, host = "archipelago.gg:55516"
        ),
        RoomWithTrackedSlots(
            room_db_id = 5, room_id = "uuid-5", room_alias = "Old", icon_name = "star",
            tracked_slots = emptyList(), is_archived = true
        )
    )

    @Test
    fun `a saved roster reads back exactly`() {
        assertEquals(roster, RosterCache.decode(RosterCache.encode(roster)))
    }

    @Test
    fun `nulls survive the round trip`() {
        val back = RosterCache.decode(RosterCache.encode(roster))!!
        val second = back[0].tracked_slots[1]
        assertNull(second.player_alias)
        assertNull(second.has_all_checks)
        assertNull(back[1].host)
    }

    @Test
    fun `a damaged file reads as no roster`() {
        assertNull(RosterCache.decode("{not json"))
    }

    @Test
    fun `an empty roster reads back empty`() {
        assertEquals(emptyList<RoomWithTrackedSlots>(), RosterCache.decode(RosterCache.encode(emptyList())))
    }
}
