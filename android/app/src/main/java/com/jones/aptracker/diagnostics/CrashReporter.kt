package com.jones.aptracker.diagnostics

import android.app.ActivityManager
import android.content.Context
import android.util.Log
import androidx.core.content.edit
import com.google.firebase.crashlytics.CustomKeysAndValues
import com.google.firebase.crashlytics.FirebaseCrashlytics
import com.jones.aptracker.BuildConfig
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

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

    /** Shared with [AppExitReporter]; both are diagnostics state that must survive reinstall-free upgrades. */
    private const val PREFS_NAME = "ap_tracker_diagnostics"
    private const val KEY_USER_CONSENT = "crash_reporting_enabled"

    /**
     * Opt-out, not opt-in: reporting is on until the user turns it off.
     *
     * This has to match what the Play Console Data safety form declares. It says collection
     * is optional, which is what obliges us to honour [setUserConsent] at all -- but nothing
     * there requires an up-front prompt, and a consent wall on first launch for crash
     * diagnostics would be a worse experience than a switch in Settings.
     */
    private const val DEFAULT_USER_CONSENT = true

    /**
     * The user's choice, surfaced to Settings.
     *
     * Backed by SharedPreferences rather than the app's DataStore because [init] runs in
     * Application.onCreate and has to decide before anything can report; DataStore reads are
     * suspending and would leave a window where collection state is simply unknown.
     */
    private val _userConsent = MutableStateFlow(DEFAULT_USER_CONSENT)
    val userConsent: StateFlow<Boolean> = _userConsent.asStateFlow()

    /**
     * False in the debug build only; the minified build reports so the release path is exercised.
     *
     * Every entry point below checks this, and so do [AppExitReporter] and the callers that
     * set custom keys, so revoking consent silences the whole surface -- not just Crashlytics'
     * own uploads.
     */
    val isEnabled: Boolean
        get() = BuildConfig.CRASH_REPORTING_ENABLED && _userConsent.value

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    /**
     * Resolved once in [init] rather than per call. Null means Firebase never came up -- most
     * likely a google-services.json with no client matching this variant's application id --
     * in which case every entry point below quietly no-ops.
     */
    @Volatile
    private var crashlytics: FirebaseCrashlytics? = null

    fun init(context: Context) {
        // Before touching Firebase: the manifest disables collection by default, so an early
        // crash between process start and this line is dropped rather than uploaded against
        // a consent value we have not read yet.
        _userConsent.value = prefs(context).getBoolean(KEY_USER_CONSENT, DEFAULT_USER_CONSENT)

        val instance = try {
            FirebaseCrashlytics.getInstance()
        } catch (e: Exception) {
            Log.w(TAG, "Crashlytics unavailable; reporting disabled for this process", e)
            return
        }
        crashlytics = instance

        applyCollectionState(context, instance)
    }

    /**
     * Records the user's choice and acts on it immediately.
     *
     * Turning it off also drops anything Crashlytics has queued but not yet sent. A report
     * captured before the user opted out would otherwise still be uploaded on the next
     * launch, which is not what "off" means to the person who chose it.
     */
    fun setUserConsent(context: Context, enabled: Boolean) {
        prefs(context).edit { putBoolean(KEY_USER_CONSENT, enabled) }
        _userConsent.value = enabled

        val instance = crashlytics ?: return
        applyCollectionState(context, instance)
        if (!isEnabled) {
            try {
                instance.deleteUnsentReports()
            } catch (e: Exception) {
                Log.w(TAG, "Could not drop unsent reports", e)
            }
        }
    }

    private fun applyCollectionState(context: Context, instance: FirebaseCrashlytics) {
        // Set explicitly rather than relying on the manifest default, so that the build flag
        // and the user's choice together are the single source of truth for whether we upload.
        instance.isCrashlyticsCollectionEnabled = isEnabled
        if (!isEnabled) return

        instance.setCustomKey("flavor", BuildConfig.FLAVOR)
        // Distinguishes minified from release, which otherwise differ only by application id.
        instance.setCustomKey("build_type", BuildConfig.BUILD_TYPE)
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

    /**
     * Breadcrumb attached to any report that follows it.
     *
     * The breadcrumb log is a fixed 64KB ring, so this is for events that happen a bounded
     * number of times per session. Anything on a hot path belongs in a custom key instead.
     */
    fun log(message: String) {
        if (!isEnabled) return
        crashlytics?.log(message)
    }

    fun setKey(key: String, value: Int) {
        if (!isEnabled) return
        crashlytics?.setCustomKey(key, value)
    }

    /**
     * Records a non-fatal with [keys] bound to this specific event.
     *
     * Session-level keys are read by Crashlytics on its own worker at write time, so events
     * reported in a batch would all land carrying the last event's values. Per-event keys are
     * still filterable in the console and cannot cross-attribute.
     */
    fun recordNonFatal(throwable: Throwable, keys: CustomKeysAndValues) {
        if (!isEnabled) return
        crashlytics?.recordException(throwable, keys)
    }

    private const val BYTES_PER_MB = 1024L * 1024L
}
