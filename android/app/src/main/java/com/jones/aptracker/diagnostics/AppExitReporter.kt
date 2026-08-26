package com.jones.aptracker.diagnostics

import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.content.Context
import android.os.Build
import android.util.Log

/**
 * Reports the previous process's death to Crashlytics on the next launch.
 *
 * Crashlytics is blind to the terminations that Play's out-of-memory filter counts: a process
 * killed by the low memory killer while cached throws nothing and runs no handler, it simply
 * stops existing. The platform records the reason and the memory footprint at death, but only
 * the *next* launch can read them back -- which is what this does.
 *
 * Requires API 30; on 26-29 there is no equivalent and this is a no-op.
 */
object AppExitReporter {

    private const val TAG = "AppExitReporter"
    private const val PREFS_NAME = "ap_tracker_diagnostics"
    private const val KEY_LAST_REPORTED_EXIT = "last_reported_exit_timestamp"

    /** The platform keeps at most 16 records; asking for 0 means "all of them". */
    private const val ALL_RECORDS = 0

    /**
     * Reads every process exit recorded since the last call and reports the notable ones.
     *
     * Blocking -- call from a background thread. Safe to call more than once: the watermark
     * makes repeat calls report nothing.
     */
    fun reportSinceLastLaunch(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return
        if (!CrashReporter.isEnabled) return

        try {
            val am = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager ?: return
            val prefs = context.applicationContext
                .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val watermark = prefs.getLong(KEY_LAST_REPORTED_EXIT, 0L)

            val exits = am.getHistoricalProcessExitReasons(context.packageName, ALL_RECORDS, ALL_RECORDS)
            if (exits.isEmpty()) return

            // Advance the watermark past everything examined, not just what was reported, so a
            // run of ignorable exits cannot make us re-scan the same records on every launch.
            var newestSeen = watermark

            for (exit in exits) {
                if (exit.timestamp <= watermark) continue
                if (exit.timestamp > newestSeen) newestSeen = exit.timestamp
                if (!AppExitReasons.isReportable(exit.reason)) continue
                report(exit)
            }

            if (newestSeen > watermark) {
                prefs.edit().putLong(KEY_LAST_REPORTED_EXIT, newestSeen).apply()
            }
        } catch (e: Exception) {
            Log.w(TAG, "Could not read historical process exit reasons", e)
        }
    }

    private fun report(exit: ApplicationExitInfo) {
        val reason = AppExitReasons.name(exit.reason)
        val state = AppExitReasons.importanceName(exit.importance)
        val pssMb = exit.pss / KB_PER_MB
        val rssMb = exit.rss / KB_PER_MB

        // Set alongside the report so the console can be sliced by the same axes Play uses:
        // which state the process was in, and how much it was holding when it died.
        CrashReporter.setKey("last_exit_reason", reason)
        CrashReporter.setKey("last_exit_state", state)
        CrashReporter.setKey("last_exit_pss_mb", pssMb.toInt())
        CrashReporter.setKey("last_exit_rss_mb", rssMb.toInt())
        CrashReporter.log(
            "Process exit: $reason in $state state, pss=${pssMb}MB rss=${rssMb}MB, " +
                "description=${exit.description ?: "none"}"
        )

        val message = "Process killed: $reason while $state (pss=${pssMb}MB, rss=${rssMb}MB)"
        CrashReporter.recordNonFatal(ProcessDeathException(message, reason, state))
        Log.w(TAG, message)
    }

    private const val KB_PER_MB = 1024L
}

/**
 * Carrier for a process death that produced no throwable of its own.
 *
 * Crashlytics groups non-fatals by stack trace, so the trace is replaced with a single
 * synthetic frame naming the reason and state. Without that, every reported termination
 * shares [AppExitReporter.report]'s frame and collapses into one undifferentiated issue.
 */
class ProcessDeathException internal constructor(
    message: String,
    reason: String,
    state: String
) : RuntimeException(message) {
    init {
        stackTrace = arrayOf(
            StackTraceElement("com.jones.aptracker.ProcessExit", reason, state, 0)
        )
    }

    override fun fillInStackTrace(): Throwable = this
}
