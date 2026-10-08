package com.jones.aptracker.ui

import com.jones.aptracker.network.Player
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The picker's "My slots" filter (#438). Its point is a short list in a room of
 * thousands, so these pin which rows survive it: tracked ones even when unticked,
 * and ticked ones even before they are saved.
 */
class PlayersFilterTest {

    private fun player(id: Int, name: String, game: String = "Some Game", tracked: Boolean = false) =
        Player(slot_id = id, name = name, game = game, is_tracked = tracked)

    private val players = listOf(
        player(1, "JonesCP", game = "Crystal Project", tracked = true),
        player(2, "Blasphemous-7", game = "Blasphemous"),
        player(3, "JonesSpinner", game = "Timespinner", tracked = true),
        player(4, "Someone", game = "Crystal Project")
    )

    private fun ids(result: List<Player>) = result.map { it.slot_id }

    @Test
    fun `off, every slot is listed`() {
        assertEquals(listOf(1, 2, 3, 4), ids(filterPlayers(players, "", false, emptyMap())))
    }

    @Test
    fun `on, only tracked slots are listed`() {
        assertEquals(listOf(1, 3), ids(filterPlayers(players, "", true, emptyMap())))
    }

    @Test
    fun `a tracked slot that was unticked stays listed until saved`() {
        assertEquals(listOf(1, 3), ids(filterPlayers(players, "", true, mapOf(1 to false, 3 to true))))
    }

    @Test
    fun `a slot ticked but not yet saved is listed`() {
        assertEquals(listOf(1, 2, 3), ids(filterPlayers(players, "", true, mapOf(2 to true))))
    }

    @Test
    fun `search applies inside the filter`() {
        assertEquals(listOf(1), ids(filterPlayers(players, "crystal", true, emptyMap())))
        assertEquals(listOf(1, 4), ids(filterPlayers(players, "  crystal ", false, emptyMap())))
    }
}
