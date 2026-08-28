package com.jones.aptracker.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Guards the three rules that decide whether a console line reads as names or as raw
 * numbers. Each of these failed silently before -- a wrong mapping still renders, it
 * just renders the wrong thing -- so they are pinned here rather than left to review.
 */
class DatapackageLookupTest {

    // ---------------------------------------------------------------
    // buildPlayerNames
    // ---------------------------------------------------------------

    @Test
    fun `player names prefer alias over the generation name`() {
        val names = buildPlayerNames(
            team = 0,
            players = listOf(ApNetworkPlayer(team = 0, slot = 1, alias = "Hyper", name = "Meow"))
        )

        assertEquals("Hyper", names["1"])
    }

    @Test
    fun `player names fall back to the generation name when the alias is blank`() {
        val names = buildPlayerNames(
            team = 0,
            players = listOf(ApNetworkPlayer(team = 0, slot = 1, alias = "  ", name = "Meow"))
        )

        assertEquals("Meow", names["1"])
    }

    @Test
    fun `player names fall back to the slot number when the server sends neither`() {
        val names = buildPlayerNames(
            team = 0,
            players = listOf(ApNetworkPlayer(team = 0, slot = 7, alias = null, name = null))
        )

        assertEquals("Player 7", names["7"])
    }

    @Test
    fun `other teams never overwrite our own slot numbers`() {
        // Slot numbers restart per team, so team 1's slot 1 collides with ours. Taking
        // both would name half the room after strangers.
        val names = buildPlayerNames(
            team = 0,
            players = listOf(
                ApNetworkPlayer(team = 0, slot = 1, alias = "Ours", name = "Ours"),
                ApNetworkPlayer(team = 1, slot = 1, alias = "Theirs", name = "Theirs"),
                ApNetworkPlayer(team = 1, slot = 2, alias = "AlsoTheirs", name = "AlsoTheirs")
            )
        )

        assertEquals("Ours", names["1"])
        assertFalse("team 1 slots leaked into the map", names.containsKey("2"))
    }

    @Test
    fun `slot zero is the server itself`() {
        val names = buildPlayerNames(team = 0, players = emptyList())

        assertEquals("Archipelago", names["0"])
    }

    // ---------------------------------------------------------------
    // buildSlotChecksums
    // ---------------------------------------------------------------

    @Test
    fun `each slot maps to the checksum of the game it plays`() {
        val checksums = buildSlotChecksums(
            slotInfo = mapOf(
                "1" to ApNetworkSlot(name = "Hyper", game = "shapez"),
                "2" to ApNetworkSlot(name = "Fire", game = "Final Fantasy")
            ),
            gameChecksums = mapOf("shapez" to "chk_shapez", "Final Fantasy" to "chk_ff")
        )

        assertEquals(mapOf("1" to "chk_shapez", "2" to "chk_ff"), checksums)
    }

    @Test
    fun `a slot whose game has no checksum is dropped rather than guessed`() {
        // Resolving it against some other game's table would print a confidently wrong
        // item name; the raw id is the honest answer.
        val checksums = buildSlotChecksums(
            slotInfo = mapOf(
                "1" to ApNetworkSlot(game = "shapez"),
                "2" to ApNetworkSlot(game = "Some Custom Apworld"),
                "3" to ApNetworkSlot(game = null)
            ),
            gameChecksums = mapOf("shapez" to "chk_shapez")
        )

        assertEquals(mapOf("1" to "chk_shapez"), checksums)
    }

    // ---------------------------------------------------------------
    // priorityChecksums
    // ---------------------------------------------------------------

    @Test
    fun `our own game and the generic package are fetched first`() {
        val priority = priorityChecksums(
            ourSlot = 2,
            slotToChecksum = mapOf("1" to "chk_shapez", "2" to "chk_ff", "3" to "chk_other"),
            genericChecksum = "chk_generic"
        )

        assertEquals(setOf("chk_ff", "chk_generic"), priority)
    }

    @Test
    fun `priority survives a room with no generic package`() {
        val priority = priorityChecksums(
            ourSlot = 1,
            slotToChecksum = mapOf("1" to "chk_shapez"),
            genericChecksum = null
        )

        assertEquals(setOf("chk_shapez"), priority)
    }

    @Test
    fun `priority is empty when our own slot is unknown`() {
        // Nothing to prioritise is fine -- the caller just fetches everything in one
        // batch, which is what it did before ordering existed.
        assertEquals(
            emptySet<String>(),
            priorityChecksums(null, mapOf("1" to "chk_shapez"), null)
        )
    }

    // ---------------------------------------------------------------
    // resolveEntityName
    // ---------------------------------------------------------------

    @Test
    fun `an id resolves within its own game`() {
        val names = mapOf("chk_a_42" to "Blue Key", "chk_b_42" to "Rusty Sword")

        assertEquals("Blue Key", resolveEntityName(names, "chk_a", null, "42"))
        assertEquals("Rusty Sword", resolveEntityName(names, "chk_b", null, "42"))
    }

    @Test
    fun `a generic Archipelago id resolves through the fallback package`() {
        // Location -1 is Cheat Console and lives only in the generic world's package,
        // but can turn up in a line about any game.
        val names = mapOf("chk_generic_-1" to "Cheat Console")

        assertEquals("Cheat Console", resolveEntityName(names, "chk_shapez", "chk_generic", "-1"))
    }

    @Test
    fun `the slot's own game wins over the generic package`() {
        val names = mapOf("chk_shapez_5" to "Belt", "chk_generic_5" to "Nothing")

        assertEquals("Belt", resolveEntityName(names, "chk_shapez", "chk_generic", "5"))
    }

    @Test
    fun `an unknown id falls through to the raw number`() {
        assertEquals("999", resolveEntityName(emptyMap(), "chk_shapez", "chk_generic", "999"))
    }

    @Test
    fun `keys from different games never collide`() {
        assertNull(mapOf(datapackageKey("chk_a", "42") to "Blue Key")[datapackageKey("chk_b", "42")])
    }
}
