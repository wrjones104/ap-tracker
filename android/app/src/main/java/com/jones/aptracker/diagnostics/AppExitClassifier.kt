package com.jones.aptracker.diagnostics

/**
 * Decides which process deaths are worth a Crashlytics report, and names them.
 *
 * Kept free of any `android.*` type so it can be unit tested. The codes mirror the frozen
 * `android.app.ApplicationExitInfo.REASON_*` constants (API 30+); the collector passes the
 * platform's raw int straight through, so the two never need translating.
 *
 * The point of this class is that Crashlytics cannot see the terminations Play's new
 * out-of-memory filter counts. An app killed by the low memory killer while cached never
 * throws, never runs an uncaught handler, and simply vanishes -- so without reading exit
 * reasons back on the next launch, the memory work is being done blind.
 */
internal object AppExitReasons {
    const val UNKNOWN = 0
    const val EXIT_SELF = 1
    const val SIGNALED = 2
    const val LOW_MEMORY = 3
    const val CRASH = 4
    const val CRASH_NATIVE = 5
    const val ANR = 6
    const val INITIALIZATION_FAILURE = 7
    const val PERMISSION_CHANGE = 8
    const val EXCESSIVE_RESOURCE_USAGE = 9
    const val USER_REQUESTED = 10
    const val USER_STOPPED = 11
    const val DEPENDENCY_DIED = 12
    const val OTHER = 13
    const val FREEZER = 14
    const val PACKAGE_STATE_CHANGE = 15
    const val PACKAGE_UPDATED = 16

    /**
     * Exits that indicate the process was taken down for resource reasons, or failed before it
     * could report for itself.
     *
     * [CRASH], [CRASH_NATIVE] and [ANR] are deliberately absent: Crashlytics reports all three
     * first-hand, and re-reporting them here would double-count every crash in the very metric
     * we are trying to read. [SIGNALED] is included despite being broad because several OEM
     * builds surface low memory kills as a SIGKILL rather than as [LOW_MEMORY]; the signal
     * description is recorded alongside so the two can be separated in the console.
     */
    private val REPORTABLE = setOf(
        SIGNALED,
        LOW_MEMORY,
        INITIALIZATION_FAILURE,
        EXCESSIVE_RESOURCE_USAGE
    )

    fun isReportable(reason: Int): Boolean = reason in REPORTABLE

    fun name(reason: Int): String = when (reason) {
        UNKNOWN -> "UNKNOWN"
        EXIT_SELF -> "EXIT_SELF"
        SIGNALED -> "SIGNALED"
        LOW_MEMORY -> "LOW_MEMORY"
        CRASH -> "CRASH"
        CRASH_NATIVE -> "CRASH_NATIVE"
        ANR -> "ANR"
        INITIALIZATION_FAILURE -> "INITIALIZATION_FAILURE"
        PERMISSION_CHANGE -> "PERMISSION_CHANGE"
        EXCESSIVE_RESOURCE_USAGE -> "EXCESSIVE_RESOURCE_USAGE"
        USER_REQUESTED -> "USER_REQUESTED"
        USER_STOPPED -> "USER_STOPPED"
        DEPENDENCY_DIED -> "DEPENDENCY_DIED"
        OTHER -> "OTHER"
        FREEZER -> "FREEZER"
        PACKAGE_STATE_CHANGE -> "PACKAGE_STATE_CHANGE"
        PACKAGE_UPDATED -> "PACKAGE_UPDATED"
        else -> "REASON_$reason"
    }

    /**
     * Coarse label for the process state at death, from `RunningAppProcessInfo.IMPORTANCE_*`.
     *
     * Play assesses dynamic memory separately per app state, so a cached-state kill and a
     * foreground kill are different findings even when the reason code matches.
     */
    fun importanceName(importance: Int): String = when {
        importance <= 0 -> "UNKNOWN"
        importance <= 125 -> "FOREGROUND"
        importance <= 200 -> "VISIBLE"
        importance <= 230 -> "PERCEPTIBLE"
        importance <= 325 -> "SERVICE"
        importance <= 400 -> "CACHED"
        else -> "IMPORTANCE_$importance"
    }
}
