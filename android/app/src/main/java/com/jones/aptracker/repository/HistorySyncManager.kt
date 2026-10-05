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
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

object HistorySyncManager {

    private const val COMPLETION_BANNER_DISPLAY_MS = 4000L
    // For workers queued without a timestamp, i.e. the periodic sync. Stamped workers use the
    // stamp instead (workerCanStandDown).
    private const val RECENT_SYNC_WINDOW_MS = 10_000L
    private const val ACTIVE_SYNC_WAIT_MS = 60_000L
    private const val ACTIVE_SYNC_POLL_MS = 500L
    private const val HINT_REPAIR_DEBOUNCE_MS = 1_000L

    private val applicationScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var activeSyncJob: Job? = null
    private var hintRepairJob: Job? = null

    @Volatile
    private var lastAttemptStartTime: Long = 0L

    @Volatile
    private var lastCompletedSyncTime: Long = 0L

    @Volatile
    private var pushSyncContext: Context? = null

    // The push-driven sync. Kept apart from _syncProgress so a push never drives the History
    // screen's progress banner, while the worker can still see that a sync is under way.
    private val pushSync = CoalescingRunner(
        scope = applicationScope,
        onFailure = { e -> Log.e("HistorySyncManager", "Push sync failed (WorkManager fallback active)", e) }
    ) {
        val appContext = pushSyncContext ?: return@CoalescingRunner
        val trackedRooms = RetrofitClient.instance.getUserTrackedSlots()
        HistoryRepository.getInstance(appContext).syncHistoryBatch(trackedRooms)
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
     * Re-download every hint once the user stops changing ignore or whitelist rules. The server
     * decides each hint's ignored and whitelisted flags from those rules, and a rule change does
     * not touch any hint's updated_at, so the delta sync never re-sends them. Every sync used to
     * do this as a side effect, before #411. Debounced so a bulk delete costs one download.
     */
    @Synchronized
    fun requestHintRepair(context: Context) {
        val appContext = context.applicationContext
        hintRepairJob?.cancel()
        hintRepairJob = applicationScope.launch {
            delay(HINT_REPAIR_DEBOUNCE_MS)
            HistoryRepository.getInstance(appContext).refreshHintHistory(null)
        }
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
