package com.jones.aptracker.repository

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/**
 * The push payload (#416): reading it, deciding whether it can stand in for a sync, and
 * turning it into the rows a sync would have stored. The sample is the shape
 * `backend/app/services/push_history.py` builds (version 2).
 */
class PushPayloadTest {

    private val sample = """
        {"v":2,"room":12,"tracker":"trk","host":"archipelago.gg","icon":"sword","alias":"Mine",
         "tracked":[1,2],
         "slots":[[1,4410],[2,null]],
         "hints_after":"2026-10-20T09:30:15.123456Z",
         "players":{"1":["Link","Hero","Zelda",false,null],"2":["Samus",null,"Metroid",true,true],
                    "3":["Ridley",null,null,false,null]},
         "items":[[4411,1,3,"Master Sword","Norfair Lava",1,2,1,"2026-10-23T12:34:56.123456Z"],
                  [4412,2,1,"Missile","Link's House",0,5,2,"2026-10-23T12:34:57Z"]],
         "hints":[[77,1,3,"Heart Container","Tourian Gate",true,1,0,"2026-10-20T09:00:00Z","2026-10-23T12:34:56.5Z"],
                  [78,3,2,"Varia Suit","Maridia",false,1,0,"2026-10-23T12:00:00Z","2026-10-23T12:00:00Z"]]}
    """.trimIndent()

    private fun payload() = parsePushPayload(sample)!!

    // --- Reading ---

    @Test
    fun readsEveryField() {
        val p = payload()
        assertEquals(12, p.roomId)
        assertEquals(setOf(1, 2), p.trackedSlots)
        assertEquals(mapOf(1 to 4410L, 2 to null), p.slots)
        assertEquals("2026-10-20T09:30:15.123456Z", p.hintsAfter)
        assertEquals(PushPlayer("Samus", null, "Metroid", true, true), p.players[2])
        assertEquals(PushItem(4411, 1, 3, "Master Sword", "Norfair Lava", 1, 2, 1, "2026-10-23T12:34:56.123456Z"), p.items[0])
        assertEquals(78, p.hints[1].id)
    }

    @Test
    fun anythingElseIsNoPayload() {
        assertNull(parsePushPayload(null))
        assertNull(parsePushPayload(""))
        assertNull(parsePushPayload("not json"))
        assertNull(parsePushPayload(sample.replace("\"v\":2", "\"v\":1")))
        assertNull(parsePushPayload(sample.replace("\"room\":12", "\"room\":\"twelve\"")))
        assertNull(parsePushPayload("{\"v\":2}"))
    }

    // --- Whether it can stand in for a sync ---

    private val coverage = Instant.parse("2026-10-20T09:30:15.123456Z")

    @Test
    fun appliesWhenEverySlotAndTheHintsFollowOn() {
        assertTrue(pushPayloadApplies(payload(), mapOf(1 to 4410L, 2 to null), coverage))
    }

    @Test
    fun aPhoneAheadOfTheBlockStillApplies() {
        // A sync already brought some of these; storing them again changes nothing.
        assertTrue(pushPayloadApplies(payload(), mapOf(1 to 4411L, 2 to 4412L), coverage))
    }

    @Test
    fun aGapInAnySlotMeansSync() {
        assertFalse(pushPayloadApplies(payload(), mapOf(1 to 4409L, 2 to null), coverage))
        // Nothing stored for a slot whose block starts after an id: the phone lacks that history.
        assertFalse(pushPayloadApplies(payload(), mapOf(1 to null, 2 to null), coverage))
    }

    @Test
    fun aSlotWhoseWholeHistoryIsHereNeedsNothing() {
        val p = payload().copy(slots = mapOf(2 to null))
        assertTrue(pushPayloadApplies(p, emptyMap(), coverage))
    }

    @Test
    fun hintsNeedCoverageUpToWhereTheyStart() {
        val p = payload()
        val local = mapOf(1 to 4410L, 2 to null)
        assertFalse(pushPayloadApplies(p, local, null))
        assertFalse(pushPayloadApplies(p, local, Instant.parse("2026-10-20T09:30:15.123455Z")))
        assertTrue(pushPayloadApplies(p, local, Instant.parse("2026-10-20T09:30:15.123456Z")))
        // The server can hand out "now" as a cursor, later than any hint.
        assertTrue(pushPayloadApplies(p, local, Instant.parse("2026-10-26T00:00:00Z")))
    }

    @Test
    fun noHintStartNeedsNoCoverage() {
        assertTrue(pushPayloadApplies(payload().copy(hintsAfter = null), mapOf(1 to 4410L), null))
    }

    @Test
    fun anUnreadableHintStartMeansSync() {
        assertFalse(pushPayloadApplies(payload().copy(hintsAfter = "yesterday"), mapOf(1 to 4410L), coverage))
    }

    @Test
    fun coverageIsTheLaterOfTheTwoCursors() {
        val early = "2026-10-20T09:30:15Z"
        val late = "2026-10-21T00:00:00.5Z"
        assertEquals(Instant.parse(late), laterCursor(early, late))
        assertEquals(Instant.parse(late), laterCursor(late, early))
        assertEquals(Instant.parse(early), laterCursor(early, null))
        assertEquals(Instant.parse(early), laterCursor("garbage", early))
        assertNull(laterCursor(null, null))
    }

    @Test
    fun newestHintChangeIsByTimeNotText() {
        assertEquals("2026-10-23T12:34:56.5Z", newestHintChange(payload()))
        assertNull(newestHintChange(payload().copy(hints = emptyList())))
    }

    // --- The rows it becomes ---

    @Test
    fun itemsBecomeTheRowsASyncStores() {
        val (sword, missile) = payload().toItemEntities()

        assertEquals(4411L, sword.id)
        assertEquals(12, sword.roomId)
        assertEquals("Link", sword.playerName)
        assertEquals("Hero", sword.playerAlias)
        assertEquals("Zelda", sword.receivingGame)
        assertEquals("Ridley", sword.senderName)
        assertEquals("Norfair Lava", sword.locationName)
        assertFalse(sword.isPlayerFinished)
        assertNull(sword.playerHasAllChecks)
        assertEquals("trk", sword.tracker_id)
        assertEquals("archipelago.gg", sword.host)
        assertEquals("sword", sword.icon_name)
        assertEquals(2, sword.receivedCount)
        assertTrue(sword.isIgnored)
        assertFalse(sword.isWhitelisted)
        assertEquals("2026-10-23T12:34:56.123456Z", sword.timestamp)

        assertTrue(missile.isPlayerFinished)
        assertEquals(true, missile.playerHasAllChecks)
        assertTrue(missile.isWhitelisted)
    }

    @Test
    fun aKnownSlotWithNoGameKeepsNullNotUnknown() {
        // As the sync derives it: Ridley is on the roster without a game.
        val asSender = payload().copy(items = listOf(payload().items[0].copy(slotId = 3, senderSlotId = 9)))
            .toItemEntities().single()
        assertNull(asSender.receivingGame)
        assertEquals("Unknown", asSender.senderGame)
        assertEquals("Player 9", asSender.senderName)
    }

    // --- Pushes that arrive late ---

    @Test
    fun onlyItemsTheSlotHasNotReachedAreStored() {
        // A sync already stored 4411; a push arriving afterwards must not put back its older values.
        val stored = itemsToStore(payload().toItemEntities(), mapOf(1 to 4411L, 2 to null))
        assertEquals(listOf(4412L), stored.map { it.id })
    }

    @Test
    fun aFoundHintIsNeverMarkedUnfoundAgain() {
        val unfoundCopy = payload().toHintEntities()[0].copy(isFound = false)
        val newHint = payload().toHintEntities()[1]

        assertEquals(listOf(newHint), hintsToStore(listOf(unfoundCopy, newHint), storedFoundIds = listOf(77)))
        // A found copy always goes in, and an unfound one goes in when nothing found is stored.
        assertEquals(2, hintsToStore(listOf(unfoundCopy.copy(isFound = true), newHint), listOf(77)).size)
        assertEquals(2, hintsToStore(listOf(unfoundCopy, newHint), emptyList()).size)
    }

    @Test
    fun pushCoverageCountsOnlyForTheSlotsItWasEarnedFor() {
        val p = payload()
        assertEquals("2026-10-21T00:00:00Z", pushCoverageStillCounts("2026-10-21T00:00:00Z", "1,2", p))
        // A slot tracked since: its hints were never carried, so the coverage says nothing about them.
        assertNull(pushCoverageStillCounts("2026-10-21T00:00:00Z", "1", p))
        assertNull(pushCoverageStillCounts("2026-10-21T00:00:00Z", null, p))
        assertNull(pushCoverageStillCounts(null, "1,2", p))
        assertEquals("1,2,10", trackedKey(setOf(10, 2, 1)))
    }

    @Test
    fun hintsAreTypedByTheTrackedSlots() {
        val (forYou, byYou) = payload().toHintEntities()

        assertEquals("for_you", forYou.hintType)
        assertEquals("Mine", forYou.roomAlias)
        assertEquals("Link", forYou.itemOwnerName)
        assertEquals("Ridley", forYou.locationOwnerName)
        assertTrue(forYou.isFound)
        assertEquals("2026-10-20T09:00:00Z", forYou.timestamp)

        assertEquals("by_you", byYou.hintType)
        assertEquals(3, byYou.itemOwnerId)
        assertEquals(2, byYou.locationOwnerId)
    }
}
