package com.jones.aptracker.diagnostics

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Guards the exit-reason triage in [AppExitReasons].
 *
 * Two ways this silently goes wrong, both invisible at runtime: reporting [AppExitReasons.CRASH]
 * or [AppExitReasons.ANR] here would double-count every crash Crashlytics already reports
 * first-hand, and dropping [AppExitReasons.LOW_MEMORY] would leave the memory work with no
 * signal at all -- which is the entire reason this code exists.
 *
 * The integer literals are the frozen `android.app.ApplicationExitInfo.REASON_*` values, spelled
 * out rather than referenced so this stays a plain JVM test with no Android stubs involved.
 */
class AppExitReasonsTest {

    @Test
    fun `resource terminations are reported`() {
        assertTrue("LOW_MEMORY is the primary signal", AppExitReasons.isReportable(3))
        assertTrue("OEMs surface LMK kills as SIGNALED", AppExitReasons.isReportable(2))
        assertTrue(AppExitReasons.isReportable(9)) // EXCESSIVE_RESOURCE_USAGE
        assertTrue(AppExitReasons.isReportable(7)) // INITIALIZATION_FAILURE
    }

    @Test
    fun `crashlytics native reports are not duplicated`() {
        assertFalse("CRASH is already reported by Crashlytics", AppExitReasons.isReportable(4))
        assertFalse("CRASH_NATIVE is already reported by Crashlytics", AppExitReasons.isReportable(5))
        assertFalse("ANR is already reported by Crashlytics", AppExitReasons.isReportable(6))
    }

    @Test
    fun `ordinary lifecycle exits are ignored`() {
        val ordinary = listOf(
            0,  // UNKNOWN
            1,  // EXIT_SELF
            8,  // PERMISSION_CHANGE
            10, // USER_REQUESTED
            11, // USER_STOPPED
            12, // DEPENDENCY_DIED
            13, // OTHER
            14, // FREEZER
            15, // PACKAGE_STATE_CHANGE
            16  // PACKAGE_UPDATED
        )
        for (reason in ordinary) {
            assertFalse(AppExitReasons.name(reason), AppExitReasons.isReportable(reason))
        }
    }

    @Test
    fun `reason codes map to the platform names`() {
        assertEquals("SIGNALED", AppExitReasons.name(2))
        assertEquals("LOW_MEMORY", AppExitReasons.name(3))
        assertEquals("ANR", AppExitReasons.name(6))
        assertEquals("PACKAGE_UPDATED", AppExitReasons.name(16))
    }

    @Test
    fun `unrecognised reason codes are labelled rather than dropped`() {
        assertEquals("REASON_99", AppExitReasons.name(99))
        assertFalse(AppExitReasons.isReportable(99))
    }

    @Test
    fun `importance buckets separate cached deaths from foreground deaths`() {
        assertEquals("FOREGROUND", AppExitReasons.importanceName(100))
        assertEquals("FOREGROUND", AppExitReasons.importanceName(125))
        assertEquals("VISIBLE", AppExitReasons.importanceName(200))
        assertEquals("PERCEPTIBLE", AppExitReasons.importanceName(230))
        assertEquals("SERVICE", AppExitReasons.importanceName(300))
        assertEquals("CACHED", AppExitReasons.importanceName(400))
        assertEquals("UNKNOWN", AppExitReasons.importanceName(0))
    }
}
