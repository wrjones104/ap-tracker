package com.jones.aptracker.diagnostics

import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.content.Context
import android.os.Build
import android.util.Log
import com.google.firebase.crashlytics.CustomKeysAndValues

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

            val selection = selectExitsToReport(
                records = exits,
                watermark = watermark,
                timestampOf = ApplicationExitInfo::getTimestamp,
                reasonOf = ApplicationExitInfo::getReason
            )

            selection.toReport.forEach(::report)

            if (selection.newWatermark > watermark) {
                prefs.edit().putLong(KEY_LAST_REPORTED_EXIT, selection.newWatermark).apply()
            }
        } catch (e: Exception) {
            Log.w(TAG, "Could not read historical process exit reasons", e)
        }
    }

    private fun report(exit: ApplicationExitInfo) {
        val reason = AppExitReasons.name(exit.reason)
        val state = AppExitReasons.importanceName(exit.importance)
        val detail = signalDetail(exit)
        val pssMb = exit.pss / KB_PER_MB
        val rssMb = exit.rss / KB_PER_MB

        // Attached to *this* event rather than set as session keys. Crashlytics reads session
        // keys on its own background worker at write time, not at call time, so when a batch of
        // exits is reported in one pass -- which is exactly what happens on a device under
        // enough memory pressure to kill us twice between launches -- every report would drain
        // carrying the last exit's numbers. Per-event keys stay sliceable in the console and
        // cannot cross-attribute.
        val keys = CustomKeysAndValues.Builder()
            .putString("exit_reason", reason)
            .putString("exit_state", state)
            .putString("exit_description", exit.description ?: "none")
            .putInt("exit_pss_mb", pssMb.toInt())
            .putInt("exit_rss_mb", rssMb.toInt())
            .putLong("exit_timestamp", exit.timestamp)
            .build()

        val message = "Process killed: $reason while $state (pss=${pssMb}MB, rss=${rssMb}MB)" +
            (exit.description?.let { ", description=$it" } ?: "")
        CrashReporter.log(message)
        CrashReporter.recordNonFatal(ProcessDeathException(message, "$reason$detail", state), keys)
        Log.w(TAG, message)
    }

    /**
     * Suffix that splits an otherwise undifferentiated reason into separate Crashlytics issues.
     *
     * SIGNALED is the broad bucket -- a swipe-away and a low memory kill both land there on some
     * OEM builds -- and grouping is by the synthetic frame, so without the signal name in it
     * every SIGNALED exit collapses into one issue and the noise cannot be told from the signal
     * without opening individual reports.
     */
    private fun signalDetail(exit: ApplicationExitInfo): String {
        if (exit.reason != AppExitReasons.SIGNALED) return ""
        val description = exit.description ?: return ""
        val token = description.uppercase().replace(NON_IDENTIFIER, "_").trim('_')
        return if (token.isEmpty()) "" else "_$token"
    }

    private val NON_IDENTIFIER = Regex("[^A-Z0-9]+")
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
