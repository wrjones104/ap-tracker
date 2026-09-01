package com.jones.aptracker.network

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pins the condition behind the watched-slot eye.
 *
 * Three screens draw that eye -- the rooms list, the slot detail header and the
 * activity feed -- and each used to spell the condition out for itself. The two
 * halves are easy to get wrong in opposite directions: dropping the mode check marks
 * every Cheese-linked slot, and dropping the Cheese check marks slots whose stored
 * "watch" describes nothing the user can currently see.
 */
class WatchedSlotTest {

    private fun slot(trackMode: String, cheese: CheeseSlotState?) = TrackedSlotDetail(
        slot_id = 1,
        player_name = "Player",
        player_alias = null,
        notify_progression = null,
        notify_useful = null,
        notify_filler = null,
        notify_trap = null,
        notify_hints = null,
        notify_hints_remote_items = null,
        notify_finished = null,
        use_condensed_messages = null,
        suppress_connected = null,
        track_mode = trackMode,
        cheese = cheese
    )

    private fun cheeseState() = CheeseSlotState(game_id = 7)

    @Test
    fun `watching a slot on a Cheese-linked room is marked`() {
        assertTrue(slot(TrackMode.WATCH, cheeseState()).isWatched)
    }

    @Test
    fun `playing is never marked`() {
        assertFalse(slot(TrackMode.PLAY, cheeseState()).isWatched)
    }

    @Test
    fun `watch mode without Cheese state is not marked`() {
        // Watch mode's whole effect is on Cheese claiming. With no linked tracker there
        // is nothing for the eye to explain, so the room reads as an ordinary one.
        assertFalse(slot(TrackMode.WATCH, null).isWatched)
    }

    @Test
    fun `the default mode is playing`() {
        // Older servers omit track_mode entirely; the row must not light up because of it.
        val defaulted = TrackedSlotDetail(
            slot_id = 1,
            player_name = "Player",
            player_alias = null,
            notify_progression = null,
            notify_useful = null,
            notify_filler = null,
            notify_trap = null,
            notify_hints = null,
            notify_hints_remote_items = null,
            notify_finished = null,
            use_condensed_messages = null,
            suppress_connected = null,
            cheese = cheeseState()
        )
        assertFalse(defaulted.isWatched)
    }
}
