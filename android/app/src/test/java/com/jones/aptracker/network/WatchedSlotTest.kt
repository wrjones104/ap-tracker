package com.jones.aptracker.network

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pins the condition behind the watched-slot eye.
 *
 * Three screens draw that eye -- the rooms list, the slot detail header and the
 * activity feed -- and each used to spell the condition out for itself, so they
 * drifted. Marking every Cheese-linked slot is the failure in one direction;
 * marking Playing rows, which is every row for a user not on Cheese, is the other.
 *
 * This used to also require the per-slot Cheese state, on the grounds that without
 * a linked tracker a stored "watch" described nothing. That held while the picker
 * refused to offer the choice before a room was linked, and stopped holding the
 * moment it did (#314): a slot set to Watching on a room still waiting to sync is
 * a real choice with a real effect, since it is what stops the link catch-up
 * claiming it. Only a Cheese-connected user can reach watch mode at all, so the
 * mode alone cannot light up a row that has no business carrying an eye.
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
    fun `watch mode is marked before the room has linked to Cheese`() {
        // Inverted from the original expectation, deliberately. The picker now offers
        // Watching on a room that has not synced yet, and that choice is what keeps
        // the link catch-up from claiming the slot -- so the eye has something real
        // to explain well before any Cheese state arrives.
        assertTrue(slot(TrackMode.WATCH, null).isWatched)
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
