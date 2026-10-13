package com.jones.aptracker.repository

import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.jones.aptracker.database.CachedTrackedSlotEntity
import com.jones.aptracker.network.SlotThresholdGroups
import com.jones.aptracker.network.ThresholdGroup
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The Milestones refresh's one-call fetch (#418). The batch response is matched to the cached
 * roster by (room, slot): a slot the response leaves out keeps its cached groups, exactly as a
 * failed per-slot fetch did, and an empty list clears groups deleted elsewhere.
 */
class MilestonesBatchFetchTest {

    private fun slot(room: Int, slot: Int) =
        CachedTrackedSlotEntity(roomDbId = room, slotId = slot, roomAlias = "R$room", playerName = "P$slot", playerAlias = null)

    private fun group(id: Int) = ThresholdGroup(id = id, name = "G$id", items = emptyList())

    private fun keys(result: List<Pair<CachedTrackedSlotEntity, List<ThresholdGroup>>>) =
        result.map { (s, groups) -> Triple(s.roomDbId, s.slotId, groups.map { it.id }) }

    @Test
    fun `each slot gets its own groups`() {
        val rows = listOf(slot(1, 1), slot(1, 2), slot(2, 1))
        val response = listOf(
            SlotThresholdGroups(2, 1, listOf(group(30))),
            SlotThresholdGroups(1, 1, listOf(group(10), group(11))),
            SlotThresholdGroups(1, 2, listOf(group(20)))
        )

        assertEquals(
            listOf(Triple(1, 1, listOf(10, 11)), Triple(1, 2, listOf(20)), Triple(2, 1, listOf(30))),
            keys(MilestonesRepository.matchGroupsToSlots(rows, response))
        )
    }

    @Test
    fun `slot 1 of one room never gets slot 1 of another`() {
        val rows = listOf(slot(1, 1), slot(2, 1))
        val response = listOf(SlotThresholdGroups(2, 1, listOf(group(30))))

        assertEquals(listOf(Triple(2, 1, listOf(30))), keys(MilestonesRepository.matchGroupsToSlots(rows, response)))
    }

    @Test
    fun `an empty list is kept, so deleted groups are cleared`() {
        val result = MilestonesRepository.matchGroupsToSlots(
            listOf(slot(1, 1)),
            listOf(SlotThresholdGroups(1, 1, emptyList()))
        )

        assertEquals(listOf(Triple(1, 1, emptyList<Int>())), keys(result))
    }

    @Test
    fun `a slot missing from the response is skipped, keeping its cache`() {
        val result = MilestonesRepository.matchGroupsToSlots(listOf(slot(1, 1), slot(1, 2)), emptyList())

        assertTrue(result.isEmpty())
    }

    @Test
    fun `slots the roster does not have are ignored`() {
        val result = MilestonesRepository.matchGroupsToSlots(
            listOf(slot(1, 1)),
            listOf(SlotThresholdGroups(9, 9, listOf(group(90))), SlotThresholdGroups(1, 1, emptyList()))
        )

        assertEquals(listOf(Triple(1, 1, emptyList<Int>())), keys(result))
    }

    @Test
    fun `the server's response shape parses`() {
        val json = """
            [{"room_db_id": 4, "slot_id": 7, "groups": [
                {"id": 12, "name": null, "is_triggered": true, "items": [
                    {"id": 5, "item_name": "Essences", "quantity": 3, "is_group": true, "acquired": null},
                    {"id": 6, "item_name": "Sword", "quantity": 1, "is_group": false, "acquired": 1}
                ]}
            ]}, {"room_db_id": 4, "slot_id": 8, "groups": []}]
        """.trimIndent()

        val parsed: List<SlotThresholdGroups> =
            Gson().fromJson(json, object : TypeToken<List<SlotThresholdGroups>>() {}.type)

        assertEquals(2, parsed.size)
        val first = parsed[0]
        assertEquals(4, first.room_db_id)
        assertEquals(7, first.slot_id)
        assertTrue(first.groups[0].is_triggered)
        assertNull(first.groups[0].items[0].acquired)
        assertEquals(1, first.groups[0].items[1].acquired)
        assertTrue(parsed[1].groups.isEmpty())
    }
}
