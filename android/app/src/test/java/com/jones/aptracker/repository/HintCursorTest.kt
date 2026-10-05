package com.jones.aptracker.repository

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Pins the guard against the server's null-cursor answer (#421).
 *
 * The scenario the PR review reproduced against the real endpoint: after a fresh login, room
 * "1" has 150 old hints and room "2" has 5 newer ones. The first 100-hint batch is all room 1,
 * and the server sets room 2's cursor to "now". Storing that cursor loses room 2's hints for
 * good, now that the full hint download no longer runs on every sync (#411).
 */
class HintCursorTest {

    private val now = "2026-10-05T12:00:00Z"
    private val oldMax = "2026-09-01T10:00:00Z"

    @Test
    fun roomWithNoCursorAndNoHintsInTheBatchKeepsAnEmptyCursor() {
        val stored = hintCursorsToStore(
            roomsSentWithoutCursor = setOf("1", "2"),
            roomsInBatch = setOf("1"),
            serverCursors = mapOf("1" to oldMax, "2" to now)
        )
        assertEquals(mapOf("1" to oldMax), stored)
    }

    @Test
    fun roomWithNoCursorStoresTheCursorOnceItsHintsArrive() {
        val stored = hintCursorsToStore(
            roomsSentWithoutCursor = setOf("2"),
            roomsInBatch = setOf("1", "2"),
            serverCursors = mapOf("1" to oldMax, "2" to "2026-09-20T08:00:00Z")
        )
        assertEquals(mapOf("1" to oldMax, "2" to "2026-09-20T08:00:00Z"), stored)
    }

    @Test
    fun roomThatSentACursorAlwaysStoresTheAnswer() {
        // An echoed or advanced cursor is safe: the server only moves it past hints it sent.
        val stored = hintCursorsToStore(
            roomsSentWithoutCursor = emptySet(),
            roomsInBatch = emptySet(),
            serverCursors = mapOf("1" to oldMax, "2" to now)
        )
        assertEquals(mapOf("1" to oldMax, "2" to now), stored)
    }
}
