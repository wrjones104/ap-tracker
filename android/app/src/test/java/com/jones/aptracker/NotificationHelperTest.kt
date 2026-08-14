package com.jones.aptracker

import org.junit.Assert.assertEquals
import org.junit.Test

class NotificationHelperTest {

    @Test
    fun testGetChannelId_explicitChannelPayload() {
        assertEquals(
            NotificationHelper.CHANNEL_PROGRESSION,
            NotificationHelper.getChannelId(NotificationHelper.CHANNEL_PROGRESSION, "anything")
        )
        assertEquals(
            NotificationHelper.CHANNEL_NON_PROGRESSION,
            NotificationHelper.getChannelId(NotificationHelper.CHANNEL_NON_PROGRESSION, "anything")
        )
        assertEquals(
            NotificationHelper.CHANNEL_HINTS,
            NotificationHelper.getChannelId(NotificationHelper.CHANNEL_HINTS, "anything")
        )
        assertEquals(
            NotificationHelper.CHANNEL_GENERAL,
            NotificationHelper.getChannelId(NotificationHelper.CHANNEL_GENERAL, "anything")
        )
    }

    @Test
    fun testGetChannelId_fallbackByType() {
        // Progression
        assertEquals(
            NotificationHelper.CHANNEL_PROGRESSION,
            NotificationHelper.getChannelId(null, "item_progression")
        )
        assertEquals(
            NotificationHelper.CHANNEL_PROGRESSION,
            NotificationHelper.getChannelId("", "item_milestone")
        )

        // Non-Progression items
        assertEquals(
            NotificationHelper.CHANNEL_NON_PROGRESSION,
            NotificationHelper.getChannelId(null, "item_useful")
        )
        assertEquals(
            NotificationHelper.CHANNEL_NON_PROGRESSION,
            NotificationHelper.getChannelId(null, "item_trap")
        )
        assertEquals(
            NotificationHelper.CHANNEL_NON_PROGRESSION,
            NotificationHelper.getChannelId(null, "item_filler")
        )

        // Hints
        assertEquals(
            NotificationHelper.CHANNEL_HINTS,
            NotificationHelper.getChannelId(null, "hint")
        )

        // General / Fallback
        assertEquals(
            NotificationHelper.CHANNEL_GENERAL,
            NotificationHelper.getChannelId(null, "player_finish")
        )
        assertEquals(
            NotificationHelper.CHANNEL_GENERAL,
            NotificationHelper.getChannelId(null, "unknown")
        )
        assertEquals(
            NotificationHelper.CHANNEL_GENERAL,
            NotificationHelper.getChannelId(null, null)
        )
    }
}
