package com.jones.aptracker.data

import com.jones.aptracker.network.RoomWithTrackedSlots
import com.jones.aptracker.network.TrackedSlotDetail
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * The saved roster (#468): what a cold Activity screen paints from before the server answers.
 * It must come back exactly as saved, never be read by a different app version (Gson would leave
 * new non-null fields null), and a damaged file must read as "no roster" rather than crash.
 */
class RosterCacheTest {

    @get:Rule
    val tmp = TemporaryFolder()

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

    // ------------------------------------------------------------------
    // Encoding
    // ------------------------------------------------------------------

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
    fun `broken json reads as no roster`() {
        assertNull(RosterCache.decode("{not json"))
    }

    // ------------------------------------------------------------------
    // Files
    // ------------------------------------------------------------------

    @Test
    fun `save then load round-trips through the file`() {
        val dir = tmp.root
        RosterCache.save(dir, 80, roster)

        assertEquals(roster, RosterCache.load(dir, 80))
        assertFalse(File(dir, "${RosterCache.fileName(80)}.tmp").exists())
    }

    @Test
    fun `a second save replaces the first`() {
        val dir = tmp.root
        RosterCache.save(dir, 80, roster)
        RosterCache.save(dir, 80, roster.take(1))

        assertEquals(roster.take(1), RosterCache.load(dir, 80))
    }

    @Test
    fun `a roster saved by another app version is never read`() {
        val dir = tmp.root
        RosterCache.save(dir, 79, roster)

        assertNull(RosterCache.load(dir, 80))
    }

    @Test
    fun `nothing saved reads as no roster`() {
        assertNull(RosterCache.load(tmp.root, 80))
    }

    @Test
    fun `a damaged file reads as no roster`() {
        val dir = tmp.root
        File(dir, RosterCache.fileName(80)).writeText("[{\"room_db_id\": 2, \"tracked_slots\": [")

        assertNull(RosterCache.load(dir, 80))
    }

    @Test
    fun `clear deletes every version's roster and nothing else`() {
        val dir = tmp.root
        RosterCache.save(dir, 79, roster)
        RosterCache.save(dir, 80, roster)
        val other = File(dir, "something_else.json").apply { writeText("{}") }

        RosterCache.clear(dir)

        assertNull(RosterCache.load(dir, 79))
        assertNull(RosterCache.load(dir, 80))
        assertTrue(other.exists())
    }
}
