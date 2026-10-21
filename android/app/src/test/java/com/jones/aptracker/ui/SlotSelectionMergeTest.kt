package com.jones.aptracker.ui

import com.jones.aptracker.network.TrackMode
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Manage Slots saves its edits onto the tracked set as it is now, not its snapshot (#477).
 * `PUT rooms/{id}/slots` replaces the set, so a stale snapshot undid changes made on another
 * device and moved Cheese claims with them.
 */
class SlotSelectionMergeTest {

    private val play = TrackMode.PLAY
    private val watch = TrackMode.WATCH

    @Test
    fun `nothing changed anywhere sends the same set and no modes`() {
        val save = mergeSlotSelection(
            loaded = setOf(1, 2), selected = setOf(1, 2), current = setOf(1, 2),
            loadedModes = mapOf(1 to play, 2 to watch), chosenModes = mapOf(1 to play, 2 to watch),
            modeCapable = setOf(1, 2)
        )
        assertEquals(setOf(1, 2), save.trackedSlotIds)
        assertEquals(emptyMap<Int, String>(), save.modes)
        assertEquals(emptySet<Int>(), save.removed)
    }

    @Test
    fun `a slot tracked on another device meanwhile is kept, with its mode left alone`() {
        val save = mergeSlotSelection(
            loaded = setOf(1), selected = setOf(1, 2), current = setOf(1, 9),
            loadedModes = mapOf(1 to play, 2 to play, 9 to play),
            chosenModes = mapOf(1 to play, 2 to play, 9 to play),
            modeCapable = setOf(1, 2, 9)
        )
        assertEquals(setOf(1, 2, 9), save.trackedSlotIds)
        assertEquals(mapOf(2 to play), save.modes)
    }

    @Test
    fun `a slot dropped on another device meanwhile is not re-tracked`() {
        val save = mergeSlotSelection(
            loaded = setOf(1, 2), selected = setOf(1, 2), current = setOf(1),
            loadedModes = mapOf(1 to play, 2 to play), chosenModes = mapOf(1 to play, 2 to play),
            modeCapable = setOf(1, 2)
        )
        assertEquals(setOf(1), save.trackedSlotIds)
        assertEquals(emptyMap<Int, String>(), save.modes)
        assertEquals(emptySet<Int>(), save.removed)
    }

    @Test
    fun `a slot unticked here is removed and reported for cleanup`() {
        val save = mergeSlotSelection(
            loaded = setOf(1, 2), selected = setOf(1), current = setOf(1, 2),
            loadedModes = emptyMap(), chosenModes = emptyMap(), modeCapable = emptySet()
        )
        assertEquals(setOf(1), save.trackedSlotIds)
        assertEquals(setOf(2), save.removed)
    }

    @Test
    fun `a mode changed here is sent and an unchanged one is not`() {
        val save = mergeSlotSelection(
            loaded = setOf(1, 2), selected = setOf(1, 2), current = setOf(1, 2),
            loadedModes = mapOf(1 to play, 2 to play), chosenModes = mapOf(1 to watch, 2 to play),
            modeCapable = setOf(1, 2)
        )
        assertEquals(mapOf(1 to watch), save.modes)
    }

    @Test
    fun `an added slot always sends a mode, defaulting to Playing`() {
        val save = mergeSlotSelection(
            loaded = emptySet(), selected = setOf(3, 4), current = emptySet(),
            loadedModes = emptyMap(), chosenModes = mapOf(4 to watch), modeCapable = setOf(3, 4)
        )
        assertEquals(mapOf(3 to play, 4 to watch), save.modes)
    }

    @Test
    fun `slots that cannot have a mode never send one`() {
        val save = mergeSlotSelection(
            loaded = setOf(1), selected = setOf(1, 2), current = setOf(1),
            loadedModes = mapOf(1 to play), chosenModes = mapOf(1 to watch, 2 to play),
            modeCapable = emptySet()
        )
        assertEquals(setOf(1, 2), save.trackedSlotIds)
        assertEquals(emptyMap<Int, String>(), save.modes)
    }

    @Test
    fun `ticking a slot another device already tracked sends this device's mode`() {
        val save = mergeSlotSelection(
            loaded = emptySet(), selected = setOf(5), current = setOf(5),
            loadedModes = mapOf(5 to play), chosenModes = mapOf(5 to watch), modeCapable = setOf(5)
        )
        assertEquals(setOf(5), save.trackedSlotIds)
        assertEquals(mapOf(5 to watch), save.modes)
    }
}
