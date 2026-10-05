package com.jones.aptracker.repository

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pins the two pieces that replaced the push path's double sync (#411): one sync per burst of
 * pushes, and a fallback worker that stands down only when a sync really did its work.
 */
class SyncCoordinationTest {

    // --- workerCanStandDown ---

    @Test
    fun failedAttemptAfterLastSuccessKeepsTheWorker() {
        // Push A synced at 1000. Push B's sync started at 1020 and failed. B's worker must run,
        // even though it was queued for A (KEEP) and A's success is recent.
        assertFalse(workerCanStandDown(now = 1030, lastAttemptStart = 1020, lastCompleted = 1000, requestedAt = 990, windowMs = 10_000))
        assertFalse(workerCanStandDown(now = 1030, lastAttemptStart = 1020, lastCompleted = 1000, requestedAt = null, windowMs = 10_000))
    }

    @Test
    fun stampedWorkerStandsDownOnlyForALaterSuccess() {
        assertTrue(workerCanStandDown(now = 2000, lastAttemptStart = 1500, lastCompleted = 1600, requestedAt = 1500, windowMs = 10_000))
        // A success before the worker was queued says nothing about the push or tap that queued it.
        assertFalse(workerCanStandDown(now = 2000, lastAttemptStart = 1000, lastCompleted = 1100, requestedAt = 1500, windowMs = 10_000))
    }

    @Test
    fun unstampedWorkerUsesTheWindow() {
        assertTrue(workerCanStandDown(now = 5_000, lastAttemptStart = 1000, lastCompleted = 1100, requestedAt = null, windowMs = 10_000))
        assertFalse(workerCanStandDown(now = 20_000, lastAttemptStart = 1000, lastCompleted = 1100, requestedAt = null, windowMs = 10_000))
    }

    @Test
    fun freshProcessRuns() {
        // After process death both clocks are zero; the worker must not stand down.
        assertFalse(workerCanStandDown(now = 50_000, lastAttemptStart = 0, lastCompleted = 0, requestedAt = 49_000, windowMs = 10_000))
        assertFalse(workerCanStandDown(now = 50_000, lastAttemptStart = 0, lastCompleted = 0, requestedAt = null, windowMs = 10_000))
    }

    // --- CoalescingRunner ---

    private suspend fun awaitIdle(runner: CoalescingRunner) {
        while (runner.isRunning) yield()
    }

    @Test
    fun burstDuringARunCostsOneRerun() = runBlocking {
        val gate = CompletableDeferred<Unit>()
        var passes = 0
        val runner = CoalescingRunner(this, onFailure = { throw AssertionError(it) }) {
            passes++
            if (passes == 1) gate.await()
        }

        assertTrue(runner.request())
        yield() // let the first pass start and park on the gate
        assertFalse(runner.request())
        assertFalse(runner.request())
        assertFalse(runner.request())

        gate.complete(Unit)
        awaitIdle(runner)
        assertEquals(2, passes)
    }

    @Test
    fun failureEndsTheRunAndALaterRequestStartsAgain() = runBlocking {
        val failures = mutableListOf<Exception>()
        var passes = 0
        val runner = CoalescingRunner(this, onFailure = { failures += it }) {
            passes++
            if (passes == 1) throw IllegalStateException("network blip")
        }

        assertTrue(runner.request())
        awaitIdle(runner)
        assertEquals(1, failures.size)
        assertFalse(runner.isRunning)

        assertTrue(runner.request())
        awaitIdle(runner)
        assertEquals(2, passes)
        assertEquals(1, failures.size)
    }

    @Test
    fun requestDuringAFailingRunIsNotLost() = runBlocking {
        val gate = CompletableDeferred<Unit>()
        var passes = 0
        val runner = CoalescingRunner(this, onFailure = { }) {
            passes++
            if (passes == 1) {
                gate.await()
                throw IllegalStateException("network blip")
            }
        }

        runner.request()
        yield()
        assertFalse(runner.request()) // a second push arrives while the first sync is failing
        gate.complete(Unit)
        awaitIdle(runner)
        // The finally block's re-check picked the second push up after the failure.
        assertEquals(2, passes)
    }

    @Test
    fun separateRequestsAfterIdleEachRun() = runBlocking {
        var passes = 0
        val runner = CoalescingRunner(this, onFailure = { throw AssertionError(it) }) { passes++ }
        runner.request()
        awaitIdle(runner)
        runner.request()
        awaitIdle(runner)
        assertEquals(2, passes)
    }
}
