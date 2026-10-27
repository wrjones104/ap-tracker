package com.jones.aptracker.repository

import android.content.Context
import android.util.Log
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.jones.aptracker.network.RetrofitClient
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch

object HistorySyncManager {

    private const val COMPLETION_BANNER_DISPLAY_MS = 4000L
    // For workers queued without a timestamp, i.e. the periodic sync. Stamped workers use the
    // stamp instead (workerCanStandDown).
    private const val RECENT_SYNC_WINDOW_MS = 10_000L
    private const val ACTIVE_SYNC_WAIT_MS = 60_000L
    private const val ACTIVE_SYNC_POLL_MS = 500L
    private const val FILTER_REPAIR_DEBOUNCE_MS = 1_000L
    // Far longer than a push takes to arrive while the app is open, which it is during a rule change.
    private const val FILTER_CHANGE_SYNC_WINDOW_MS = 120_000L

    // Its own file, not the sync watermarks: clearing local history resets those, and the
    // re-downloaded items then carry current flags anyway.
    private const val FILTER_FLAG_PREFS = "ap_tracker_filter_flags"
    private const val KEY_ITEM_FLAGS_REPAIRED = "item_filter_flags_repaired_464"

    private val applicationScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var activeSyncJob: Job? = null
    private var filterRepairJob: Job? = null

    @Volatile
    private var lastAttemptStartTime: Long = 0L

    @Volatile
    private var lastCompletedSyncTime: Long = 0L

    @Volatile
    private var pushSyncContext: Context? = null

    @Volatile
    private var lastFilterRuleChange: Long = 0L

    // The push-driven sync. Kept apart from _syncProgress so a push never drives the History
    // screen's progress banner, while the worker can still see that a sync is under way.
    private val pushSync = CoalescingRunner(
        scope = applicationScope,
        onFailure = { e -> Log.e("HistorySyncManager", "Push sync failed (WorkManager fallback active)", e) }
    ) {
        val appContext = pushSyncContext ?: return@CoalescingRunner
        val trackedRooms = RetrofitClient.instance.getUserTrackedSlots()
        val repository = HistoryRepository.getInstance(appContext)
        repository.syncHistoryBatch(trackedRooms)
        repairItemFlagsIfDue(appContext, repository, userInitiated = false)
        markSyncCompleted()
        com.jones.aptracker.widget.RecentItemsWidgetUpdater.update(appContext)
        com.jones.aptracker.widget.MilestonesWidgetUpdater.refreshDataAndUpdate(appContext, trackedRooms)
        Log.d("HistorySyncManager", "Push sync completed.")
    }

    private val _syncProgress = MutableStateFlow(SyncProgressState())
    val syncProgress: StateFlow<SyncProgressState> = _syncProgress

    fun isSyncActive(): Boolean = _syncProgress.value.isSyncing || pushSync.isRunning

    fun markSyncCompleted() {
        lastCompletedSyncTime = System.currentTimeMillis()
    }

    /**
     * Whether a worker can stand down because an in-process sync has it covered.
     *
     * Waits out a sync that is still running rather than skipping straight away, then defers to
     * workerCanStandDown, so the worker stays a real fallback when that sync fails. Before #411
     * the push path's in-process sync never registered here at all, so every push ran the whole
     * sync twice.
     *
     * @param requestedAt When the worker was queued, for workers that carry the stamp.
     */
    suspend fun shouldSkipWorker(requestedAt: Long? = null): Boolean {
        val deadline = System.currentTimeMillis() + ACTIVE_SYNC_WAIT_MS
        while (isSyncActive() && System.currentTimeMillis() < deadline) {
            delay(ACTIVE_SYNC_POLL_MS)
        }
        // Still running after the wait: a long backfill. It owns the work.
        if (isSyncActive()) return true
        return workerCanStandDown(
            now = System.currentTimeMillis(),
            lastAttemptStart = lastAttemptStartTime,
            lastCompleted = lastCompletedSyncTime,
            requestedAt = requestedAt,
            windowMs = RECENT_SYNC_WINDOW_MS
        )
    }

    /**
     * Sync after a push: catch the local history and the widgets up with what the push announced.
     *
     * A push that lands while this sync runs folds into one rerun (CoalescingRunner). A
     * WorkManager job is queued behind it for when the process dies or the sync fails.
     */
    fun syncForPush(context: Context) {
        val appContext = context.applicationContext
        pushSyncContext = appContext
        lastAttemptStartTime = System.currentTimeMillis()
        enqueueFallbackWorker(appContext, roomId = null)
        if (!pushSync.request()) {
            Log.d("HistorySyncManager", "Push sync already running; folded into a rerun.")
        }
    }

    /**
     * After a push: store the items and hint changes it carried when they follow on from what the
     * phone has, else sync as before ([syncForPush]). Either way the widgets catch up.
     *
     * Storing what the push carried makes no request at all (#416), which matters now that the
     * app handles every push, in the background too (#501). The Milestones widget still refreshes
     * its own cache when that is stale, as it does after a sync.
     */
    suspend fun handlePush(context: Context, historyJson: String?) {
        val appContext = context.applicationContext
        val payload = parsePushPayload(historyJson)
        val rulesSettled = filterRulesSettled(System.currentTimeMillis(), lastFilterRuleChange, FILTER_CHANGE_SYNC_WINDOW_MS)
        if (payload != null && !rulesSettled) {
            Log.d("HistorySyncManager", "An ignore or whitelist rule changed just now; syncing instead of storing the push's items.")
        } else if (payload != null) {
            val applied = try {
                HistoryRepository.getInstance(appContext).applyPushPayload(payload)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.w("HistorySyncManager", "Could not store the push's items; syncing instead.", e)
                false
            }
            if (applied) {
                Log.d("HistorySyncManager", "Stored ${payload.items.size} items and ${payload.hints.size} hints from the push; no sync needed.")
                // Awaited: it is local and quick, and the caller holds the process for it. The
                // Milestones refresh is not, as it may call the server.
                com.jones.aptracker.widget.RecentItemsWidgetUpdater.update(appContext)
                com.jones.aptracker.widget.MilestonesWidgetUpdater.refreshDataAndUpdateAsync(appContext)
                return
            }
            Log.d("HistorySyncManager", "The push's items do not follow on from local history, or a sync holds it; syncing.")
        }
        syncForPush(appContext)
    }

    private val _filterFlagsChanged = MutableSharedFlow<Unit>(extraBufferCapacity = 1)

    /**
     * Emits after cached items were re-flagged for a rule change, so the Activity screen, which
     * reads items once rather than as a Flow, can reload them (#464).
     */
    val filterFlagsChanged: SharedFlow<Unit> = _filterFlagsChanged.asSharedFlow()

    /**
     * Re-applies ignore and whitelist rules to everything already on the phone, once the user
     * stops changing them. The server decides each item's and hint's flags from those rules when
     * it sends them, and the delta sync never re-sends either after a rule change. Debounced so a
     * bulk delete costs one round.
     *
     * Hints are re-downloaded whole (every sync used to do this as a side effect, before #411).
     * Items are re-flagged from the ids the server says match now, which is far smaller than the
     * items themselves (#464).
     */
    @Synchronized
    fun requestFilterRepair(context: Context) {
        val appContext = context.applicationContext
        lastFilterRuleChange = System.currentTimeMillis()
        filterRepairJob?.cancel()
        filterRepairJob = applicationScope.launch {
            delay(FILTER_REPAIR_DEBOUNCE_MS)
            val repository = HistoryRepository.getInstance(appContext)
            repository.refreshHintHistory(null)
            if (repository.refreshItemFilterFlags()) {
                _filterFlagsChanged.tryEmit(Unit)
                com.jones.aptracker.widget.RecentItemsWidgetUpdater.update(appContext)
            }
        }
    }

    /**
     * Re-flags cached items after a sync when [itemFlagRepairDue] says so: on a refresh the user
     * asked for, and once after the upgrade that brought the re-flag. Runs after the sync, so the
     * items it just stored are covered too. Callers redraw the widget afterwards.
     */
    private suspend fun repairItemFlagsIfDue(
        appContext: Context,
        repository: HistoryRepository,
        userInitiated: Boolean
    ) {
        val prefs = appContext.getSharedPreferences(FILTER_FLAG_PREFS, Context.MODE_PRIVATE)
        if (!itemFlagRepairDue(userInitiated, prefs.getBoolean(KEY_ITEM_FLAGS_REPAIRED, false))) return
        if (!repository.refreshItemFilterFlags()) return
        prefs.edit().putBoolean(KEY_ITEM_FLAGS_REPAIRED, true).apply()
        _filterFlagsChanged.tryEmit(Unit)
    }

    /**
     * @param repairHints Also re-download every hint for the scope. Only for a refresh the user
     * asked for: the delta sync already carries new hints and found-status changes, and this full
     * download was most of the app's data use when it ran on every sync (#411).
     */
    fun triggerSync(
        context: Context,
        roomId: Int? = null,
        repairHints: Boolean = false,
        onBatchReceived: (() -> Unit)? = null
    ) {
        val appContext = context.applicationContext
        Log.d("HistorySyncManager", "Triggering sync for room: ${roomId ?: "Global"} in application scope...")

        lastAttemptStartTime = System.currentTimeMillis()

        // Mark sync active synchronously FIRST to prevent WorkManager from racing and acquiring the syncMutex
        _syncProgress.value = _syncProgress.value.copy(
            isSyncing = true,
            isJustCompleted = false
        )

        // 1. Enqueue WorkManager job as background fallback (runs if process dies / phone locks)
        enqueueFallbackWorker(appContext, roomId)

        // 2. Launch primary sync in ApplicationScope for live foreground UI updates
        activeSyncJob?.cancel()
        activeSyncJob = applicationScope.launch {
            try {
                val repository = HistoryRepository.getInstance(appContext)
                val apiService = RetrofitClient.instance

                val trackedRooms = apiService.getUserTrackedSlots()

                val relevantRooms = if (roomId != null) {
                    trackedRooms.filter { it.room_db_id == roomId }
                } else {
                    trackedRooms.filter { !it.is_archived }
                }

                val totalServerItems = relevantRooms.sumOf { room -> room.tracked_slots.sumOf { slot -> slot.item_count } }
                val localItemCount = repository.getLocalItemCount(roomId)
                val totalDelta = maxOf(0, totalServerItems - localItemCount)
                val hasPendingBackfill = relevantRooms.any { room -> room.tracked_slots.any { slot -> slot.needs_backfill } }

                _syncProgress.value = SyncProgressState(
                    isSyncing = true,
                    loopsCompleted = 0,
                    itemsFetchedInSync = 0,
                    totalDeltaToFetch = totalDelta,
                    progressPercentage = if (totalDelta == 0) 100 else 0,
                    serverReportedTotalItems = totalServerItems,
                    localItemCount = localItemCount,
                    hasPendingBackfill = hasPendingBackfill,
                    isJustCompleted = false
                )

                var itemsFetchedTotal = 0

                if (repairHints) {
                    repository.refreshHintHistory(roomId)
                }

                repository.syncHistoryBatch(trackedRooms, priorityRoomId = roomId) { itemsFetchedThisBatch, loopCount, hasMore ->
                    itemsFetchedTotal += itemsFetchedThisBatch
                    val delta = _syncProgress.value.totalDeltaToFetch
                    val pct = if (delta > 0) minOf(100, (itemsFetchedTotal * 100) / delta) else 100
                    _syncProgress.value = _syncProgress.value.copy(
                        loopsCompleted = loopCount,
                        itemsFetchedInSync = itemsFetchedTotal,
                        progressPercentage = pct,
                        hasPendingBackfill = hasMore || hasPendingBackfill
                    )
                    onBatchReceived?.invoke()
                }

                // Pull-to-refresh repairs item flags as it does hints; any sync also runs the
                // one-time repair after the upgrade (#464).
                repairItemFlagsIfDue(appContext, repository, userInitiated = repairHints)

                val finalItemsTotal = itemsFetchedTotal
                val finalPct = if (totalDelta > 0) minOf(100, (finalItemsTotal * 100) / totalDelta) else 100
                markSyncCompleted()

                _syncProgress.value = _syncProgress.value.copy(
                    isSyncing = false,
                    isJustCompleted = true,
                    itemsFetchedInSync = finalItemsTotal,
                    progressPercentage = finalPct,
                    hasPendingBackfill = false
                )

                onBatchReceived?.invoke()
                com.jones.aptracker.widget.RecentItemsWidgetUpdater.updateAsync(appContext)
                // The Milestones widget reads only local data, so its cache has to be refreshed
                // here or it would redraw stale milestones. `trackedRooms` is reused to avoid
                // re-fetching the large roster response.
                com.jones.aptracker.widget.MilestonesWidgetUpdater.refreshDataAndUpdateAsync(appContext, trackedRooms)

                // Auto-dismiss completion banner state after delay
                applicationScope.launch {
                    delay(COMPLETION_BANNER_DISPLAY_MS)
                    if (_syncProgress.value.isJustCompleted) {
                        _syncProgress.value = _syncProgress.value.copy(isJustCompleted = false)
                    }
                }

            } catch (e: Exception) {
                Log.e("HistorySyncManager", "Application-scoped history sync failed", e)
                _syncProgress.value = _syncProgress.value.copy(isSyncing = false)
            }
        }
    }

    private fun enqueueFallbackWorker(appContext: Context, roomId: Int?) {
        try {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()

            val workDataBuilder = Data.Builder()
                .putLong(HistorySyncWorker.KEY_REQUESTED_AT, System.currentTimeMillis())
            roomId?.let { workDataBuilder.putInt("target_room_id", it) }

            val syncWorkRequest = OneTimeWorkRequestBuilder<HistorySyncWorker>()
                .setConstraints(constraints)
                .setInputData(workDataBuilder.build())
                .build()

            // KEEP: a burst of pushes queues one fallback, not one per push.
            WorkManager.getInstance(appContext).enqueueUniqueWork(
                "history_sync_work_${roomId ?: "global"}",
                ExistingWorkPolicy.KEEP,
                syncWorkRequest
            )
            Log.d("HistorySyncManager", "Enqueued HistorySyncWorker with WorkManager.")
        } catch (e: Exception) {
            Log.e("HistorySyncManager", "Failed to enqueue WorkManager sync work", e)
        }
    }
}
