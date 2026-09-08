package com.jones.aptracker.network

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Pins what may be done with a stashed guest token at a given age.
 *
 * Everything that went wrong in review was a decision rather than a mechanism: expiry
 * deleted the stash instead of refusing to send it, and both callers asked the same
 * question through the same getter. Three states rather than a nullable token is what
 * separates "too old to present" from "not there", and only the first of those still
 * has an account behind it.
 */
class UpgradeTokenStateTest {

    private val now = 1_700_000_000_000L

    @Test
    fun `nothing stashed`() {
        assertEquals(UpgradeTokenState.NONE, upgradeTokenState(hasToken = false, stashedAt = now, now = now))
        assertEquals(UpgradeTokenState.NONE, upgradeTokenState(hasToken = false, stashedAt = null, now = now))
    }

    @Test
    fun `a fresh stash may be presented`() {
        assertEquals(UpgradeTokenState.USABLE, upgradeTokenState(hasToken = true, stashedAt = now, now = now))
    }

    @Test
    fun `a slow signup still fits inside the window`() {
        // An email verification and a 2FA prompt inside the Discord flow. The half hour
        // this started at failed exactly this user, and failed them by creating a second
        // account rather than by saying so.
        val fortyMinutes = 40L * 60L * 1000L
        assertEquals(
            UpgradeTokenState.USABLE,
            upgradeTokenState(hasToken = true, stashedAt = now - fortyMinutes, now = now)
        )
    }

    @Test
    fun `past the window it is stale, not gone`() {
        assertEquals(
            UpgradeTokenState.STALE,
            upgradeTokenState(hasToken = true, stashedAt = now - UPGRADE_TOKEN_TTL_MS - 1, now = now)
        )
    }

    @Test
    fun `an undated stash is stale`() {
        // The token outlived the timestamp written with it, so there is no telling how old
        // it is. Refusing to send it is safe; deleting it would not be.
        assertEquals(
            UpgradeTokenState.STALE,
            upgradeTokenState(hasToken = true, stashedAt = null, now = now)
        )
    }

    @Test
    fun `a clock that moved backwards does not expire a stash`() {
        // Timezone corrections and NTP steps move the wall clock in both directions. A
        // negative age is not an old token, and treating it as one would cost the user
        // their upgrade for no reason.
        assertEquals(
            UpgradeTokenState.USABLE,
            upgradeTokenState(hasToken = true, stashedAt = now + 60_000L, now = now)
        )
    }
}
