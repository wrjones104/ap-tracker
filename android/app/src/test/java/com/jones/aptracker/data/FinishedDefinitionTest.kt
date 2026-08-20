package com.jones.aptracker.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Guards the client half of the evaluator against drifting from the server's
 * `evaluate_finished` in `backend/app/utils.py`.
 *
 * The two deciding differently is not a cosmetic bug: the server suppresses
 * notifications for slots it considers finished while the client decides what to show,
 * so a disagreement means either a hidden slot that still notifies or a visible slot
 * that has gone silent. The truth table here is deliberately the same shape as
 * `TestEvaluateFinished` in `backend/tests/test_finished_definition.py`.
 */
class FinishedDefinitionTest {

    @Test
    fun `truth table matches the server`() {
        // definition to (goaled+checks, goaled only, checks only, neither)
        val expected = mapOf(
            FinishedDefinition.GOAL to listOf(true, true, false, false),
            FinishedDefinition.ALL_CHECKS to listOf(true, false, true, false),
            FinishedDefinition.BOTH to listOf(true, false, false, false),
            FinishedDefinition.EITHER to listOf(true, true, true, false)
        )
        val facts = listOf(
            true to true,
            true to false,
            false to true,
            false to false
        )

        for ((definition, results) in expected) {
            facts.forEachIndexed { index, (goaled, allChecks) ->
                assertEquals(
                    "$definition with goaled=$goaled allChecks=$allChecks",
                    results[index],
                    definition.evaluate(goaled, allChecks)
                )
            }
        }
    }

    @Test
    fun `unknown checks degrade every definition to goal only`() {
        // Null is "the server has no check counts for this room", not "still sending".
        // Treating it as false would hide nothing and show every goaled slot as unfinished.
        for (definition in FinishedDefinition.entries) {
            assertTrue("$definition should report a goaled slot finished", definition.evaluate(true, null))
            assertFalse("$definition should not invent a finish", definition.evaluate(false, null))
        }
    }

    @Test
    fun `unknown is distinct from false`() {
        assertFalse(FinishedDefinition.ALL_CHECKS.evaluate(true, false))
        assertTrue(FinishedDefinition.ALL_CHECKS.evaluate(true, null))
    }

    @Test
    fun `unrecognized wire values fall back to goal`() {
        // Forward compatibility: the server can ship a new criterion before this build
        // knows about it, and an old build must degrade rather than misfilter.
        assertEquals(FinishedDefinition.GOAL, FinishedDefinition.fromWire("something_new"))
        assertEquals(FinishedDefinition.GOAL, FinishedDefinition.fromWire(null))
        assertEquals(FinishedDefinition.GOAL, FinishedDefinition.fromWire(""))
    }

    @Test
    fun `every wire value round trips`() {
        for (definition in FinishedDefinition.entries) {
            assertEquals(definition, FinishedDefinition.fromWire(definition.wireValue))
        }
    }

    @Test
    fun `wire values match the server's valid set`() {
        // VALID_FINISHED_DEFINITIONS in backend/app/utils.py.
        assertEquals(
            setOf("goal", "all_checks", "both", "either"),
            FinishedDefinition.entries.map { it.wireValue }.toSet()
        )
    }

    @Test
    fun `resolver prefers the slot override over the default`() {
        val resolver = FinishedResolver(
            FinishedDefinition.GOAL,
            mapOf("7:2" to FinishedDefinition.BOTH)
        )

        // Goaled but still sending: hidden under the default, visible under the override.
        assertTrue(resolver.isFinished(roomDbId = 7, slotId = 1, isGoaled = true, hasAllChecks = false))
        assertFalse(resolver.isFinished(roomDbId = 7, slotId = 2, isGoaled = true, hasAllChecks = false))
    }

    @Test
    fun `resolver falls back to the default when the slot is unknown`() {
        val resolver = FinishedResolver(
            FinishedDefinition.BOTH,
            mapOf("7:2" to FinishedDefinition.GOAL)
        )

        assertFalse(resolver.isFinished(roomDbId = null, slotId = null, isGoaled = true, hasAllChecks = false))
        assertFalse(resolver.isFinished(roomDbId = 9, slotId = 4, isGoaled = true, hasAllChecks = false))
    }
}
