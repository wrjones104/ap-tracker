package com.jones.aptracker.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Two slots with the same name in different rooms used to share one Activity filter chip,
 * and tapping it showed both slots' items (#376). Each room's slot now gets its own chip,
 * labelled with the room only when a name is shared.
 */
class PlayerFilterChipTest {

    private val roomNames = mapOf(1 to "Async A", 2 to "Async B")

    @Test
    fun sharedNamesAreLabelledWithTheirRoom() {
        val chips = listOf(
            PlayerDisplayInfo("PoubelliRefunct", null, roomId = 1),
            PlayerDisplayInfo("PoubelliRefunct", null, roomId = 2),
            PlayerDisplayInfo("Solo", null, roomId = 1),
        ).withRoomLabelsOnSharedNames(roomNames)

        assertEquals(listOf("Async A", "Async B", null), chips.map { it.roomLabel })
    }

    @Test
    fun aRoomMissingFromTheMapStillGetsALabel() {
        val chips = listOf(
            PlayerDisplayInfo("Twin", null, roomId = 1),
            PlayerDisplayInfo("Twin", null, roomId = 9),
        ).withRoomLabelsOnSharedNames(roomNames)

        assertEquals("Room 9", chips[1].roomLabel)
    }

    @Test
    fun aKeyMatchesOnlyItsOwnRoom() {
        val key = PlayerKey(1, "PoubelliRefunct")

        assertTrue(key.matches(1, "PoubelliRefunct"))
        assertFalse(key.matches(2, "PoubelliRefunct"))
        assertFalse(key.matches(1, "Other"))
    }

    @Test
    fun aKeyWithoutARoomMatchesTheNameAnywhere() {
        val key = PlayerKey(null, "PoubelliRefunct")

        assertTrue(key.matches(1, "PoubelliRefunct"))
        assertTrue(key.matches(2, "PoubelliRefunct"))
        assertNull(PlayerDisplayInfo("Solo", null).roomLabel)
    }
}
