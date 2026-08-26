package com.jones.aptracker.diagnostics

import android.app.ActivityManager
import android.content.Context
import android.util.Log
import com.google.firebase.crashlytics.FirebaseCrashlytics
import com.jones.aptracker.BuildConfig

/**
 * Thin front door onto Crashlytics.
 *
 * Everything routes through here rather than calling [FirebaseCrashlytics] directly so that
 * the debug build can be silenced in one place, and so a Crashlytics initialization failure
 * degrades to a log line instead of taking down the app that is trying to report the problem.
 *
 * The memory keys set by [init] exist because Play's February 2027 thresholds are assessed
 * per device RAM bucket. Recording the bucket on every report is what lets a spike in
 * [AppExitReporter] terminations be sliced the same way Play slices it -- otherwise a
 * regression that only shows up on 4GB devices is invisible in an aggregate crash count.
 */
object CrashReporter {

    private const val TAG = "CrashReporter"

    /** False in the debug build only; the minified build reports so the release path is exercised. */
    val isEnabled: Boolean get() = BuildConfig.CRASH_REPORTING_ENABLED

    private val crashlytics: FirebaseCrashlytics?
        get() = try {
            FirebaseCrashlytics.getInstance()
        } catch (e: IllegalStateException) {
            // Firebase not initialized -- happens if google-services.json has no matching client.
            Log.w(TAG, "Crashlytics unavailable", e)
            null
        }

    fun init(context: Context) {
        val instance = crashlytics ?: return
        // Set explicitly rather than relying on the manifest default, so that flipping
        // CRASH_REPORTING_ENABLED is the single source of truth for whether we upload.
        instance.isCrashlyticsCollectionEnabled = isEnabled
        if (!isEnabled) return

        instance.setCustomKey("flavor", BuildConfig.FLAVOR)
        instance.setCustomKey("version_name", BuildConfig.VERSION_NAME)
        recordDeviceMemoryProfile(context, instance)
    }

    private fun recordDeviceMemoryProfile(context: Context, instance: FirebaseCrashlytics) {
        try {
            val am = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager ?: return
            val memoryInfo = ActivityManager.MemoryInfo()
            am.getMemoryInfo(memoryInfo)
            instance.setCustomKey("device_total_ram_mb", (memoryInfo.totalMem / BYTES_PER_MB).toInt())
            instance.setCustomKey("device_low_ram", am.isLowRamDevice)
            instance.setCustomKey("heap_limit_mb", am.memoryClass)
            instance.setCustomKey("heap_limit_large_mb", am.largeMemoryClass)
        } catch (e: Exception) {
            Log.w(TAG, "Could not read device memory profile", e)
        }
    }

    /** Breadcrumb attached to any report that follows it. */
    fun log(message: String) {
        if (!isEnabled) return
        crashlytics?.log(message)
    }

    fun setKey(key: String, value: Int) {
        if (!isEnabled) return
        crashlytics?.setCustomKey(key, value)
    }

    fun setKey(key: String, value: String) {
        if (!isEnabled) return
        crashlytics?.setCustomKey(key, value)
    }

    fun recordNonFatal(throwable: Throwable) {
        if (!isEnabled) return
        crashlytics?.recordException(throwable)
    }

    private const val BYTES_PER_MB = 1024L * 1024L
}
