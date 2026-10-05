package com.jones.aptracker.repository

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Runs [block] on [scope], folding any requests that arrive while it runs into one more pass.
 *
 * Pushes arrive in bursts. Without this each push would start its own sync; with it, a burst
 * costs one rerun after the current pass. A failure is handed to [onFailure] and ends the run;
 * a request made after that starts a fresh one.
 */
class CoalescingRunner(
    private val scope: CoroutineScope,
    private val onFailure: (Exception) -> Unit,
    private val block: suspend () -> Unit
) {
    private val running = AtomicBoolean(false)
    private val requested = AtomicBoolean(false)

    val isRunning: Boolean get() = running.get()

    /** Returns true if this call started a run, false if it was folded into one already running. */
    fun request(): Boolean {
        requested.set(true)
        if (!running.compareAndSet(false, true)) return false
        scope.launch {
            try {
                while (requested.getAndSet(false)) {
                    block()
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                onFailure(e)
            } finally {
                running.set(false)
                // A request that arrived between the loop's last check and the line above found
                // the run still marked running and only set the flag. Pick it up here.
                if (requested.get()) request()
            }
        }
        return true
    }
}

/**
 * Whether a sync worker can stand down because an in-process sync already did its work.
 * Called once no sync is running.
 *
 * - A sync attempt that started after the last success has failed (or was cancelled), so the
 *   worker is the fallback and must run. Checked first because WorkManager's KEEP policy can
 *   hand a later push's failure to a worker queued for an earlier push.
 * - A worker stamped with when it was queued stands down only for a success after that. An
 *   earlier success says nothing about the push or tap that queued it.
 * - An unstamped worker (the periodic sync) stands down for any success within [windowMs].
 */
fun workerCanStandDown(
    now: Long,
    lastAttemptStart: Long,
    lastCompleted: Long,
    requestedAt: Long?,
    windowMs: Long
): Boolean {
    if (lastAttemptStart > lastCompleted) return false
    if (requestedAt != null) return lastCompleted >= requestedAt
    return now - lastCompleted < windowMs
}
