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
import java.util.concurrent.atomic.AtomicBoolean

object HistorySyncManager {

    private const val COMPLETION_BANNER_DISPLAY_MS = 4000L
    private const val RECENT_SYNC_WINDOW_MS = 60_000L
    private const val ACTIVE_SYNC_WAIT_MS = 60_000L
    private const val ACTIVE_SYNC_POLL_MS = 500L

    private val applicationScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var activeSyncJob: Job? = null

    @Volatile
    private var lastCompletedSyncTime: Long = 0L

    // The push-driven sync. Kept apart from _syncProgress so a push never drives the History
    // screen's progress banner, while the worker can still see that a sync is under way.
    private val pushSyncRunning = AtomicBoolean(false)
    private val pushSyncRequested = AtomicBoolean(false)

    private val _syncProgress = MutableStateFlow(SyncProgressState())
    val syncProgress: StateFlow<SyncProgressState> = _syncProgress

    fun isSyncActive(): Boolean = _syncProgress.value.isSyncing || pushSyncRunning.get()

    fun markSyncCompleted() {
        lastCompletedSyncTime = System.currentTimeMillis()
    }

    /**
     * Whether a worker can stand down because an in-process sync has it covered.
     *
     * Waits out a sync that is still running rather than skipping straight away, so the worker
     * stays a real fallback: if that sync fails, nothing marks it completed and the worker runs.
     * Before #411 the push path's in-process sync never registered here at all, so every push
     * ran the whole sync twice.
     */
    suspend fun shouldSkipWorker(): Boolean {
        val deadline = System.currentTimeMillis() + ACTIVE_SYNC_WAIT_MS
        while (isSyncActive() && System.currentTimeMillis() < deadline) {
            delay(ACTIVE_SYNC_POLL_MS)
        }
        // Still running after the wait: a long backfill. It owns the work.
        if (isSyncActive()) return true
        return System.currentTimeMillis() - lastCompletedSyncTime < RECENT_SYNC_WINDOW_MS
    }

    /**
     * Sync after a push: catch the local history and the widgets up with what the push announced.
     *
     * Pushes arrive in bursts. A push that lands while this sync runs only flags a rerun, so a
     * burst costs one extra pass rather than one sync per push. A WorkManager job is enqueued as
     * the fallback for when the process dies first.
     */
    fun syncForPush(context: Context) {
        val appContext = context.applicationContext
        pushSyncRequested.set(true)
        if (!pushSyncRunning.compareAndSet(false, true)) {
            Log.d("HistorySyncManager", "Push sync already running; flagged a rerun.")
            return
        }

        enqueueFallbackWorker(appContext, roomId = null)

        applicationScope.launch {
            try {
                while (pushSyncRequested.getAndSet(false)) {
                    val repository = HistoryRepository.getInstance(appContext)
                    val trackedRooms = RetrofitClient.instance.getUserTrackedSlots()
                    repository.syncHistoryBatch(trackedRooms)
                    markSyncCompleted()
                    com.jones.aptracker.widget.RecentItemsWidgetUpdater.update(appContext)
                    com.jones.aptracker.widget.MilestonesWidgetUpdater.refreshDataAndUpdate(appContext, trackedRooms)
                }
                Log.d("HistorySyncManager", "Push sync completed.")
            } catch (e: Exception) {
                Log.e("HistorySyncManager", "Push sync failed (WorkManager fallback active)", e)
            } finally {
                pushSyncRunning.set(false)
                // A push that arrived between the loop's last check and the line above found the
                // sync still marked running and only set the flag. Pick it up here.
                if (pushSyncRequested.get()) syncForPush(appContext)
            }
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
