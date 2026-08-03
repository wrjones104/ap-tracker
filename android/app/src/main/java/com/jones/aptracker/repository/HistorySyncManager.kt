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
    private const val RECENT_SYNC_WINDOW_MS = 10_000L

    private val applicationScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var activeSyncJob: Job? = null

    @Volatile
    private var lastCompletedSyncTime: Long = 0L

    private val _syncProgress = MutableStateFlow(SyncProgressState())
    val syncProgress: StateFlow<SyncProgressState> = _syncProgress

    fun isSyncActive(): Boolean = _syncProgress.value.isSyncing

    fun shouldSkipWorker(): Boolean {
        return isSyncActive() || (System.currentTimeMillis() - lastCompletedSyncTime < RECENT_SYNC_WINDOW_MS)
    }

    fun triggerSync(
        context: Context,
        roomId: Int? = null,
        onBatchReceived: (() -> Unit)? = null
    ) {
        val appContext = context.applicationContext
        Log.d("HistorySyncManager", "Triggering sync for room: ${roomId ?: "Global"} in application scope...")

        // 1. Enqueue WorkManager job as background fallback (runs if process dies / phone locks)
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

            WorkManager.getInstance(appContext).enqueueUniqueWork(
                "history_sync_work_${roomId ?: "global"}",
                ExistingWorkPolicy.REPLACE,
                syncWorkRequest
            )
            Log.d("HistorySyncManager", "Enqueued HistorySyncWorker with WorkManager.")
        } catch (e: Exception) {
            Log.e("HistorySyncManager", "Failed to enqueue WorkManager sync work", e)
        }

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

                repository.refreshHintHistory(roomId)

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
                lastCompletedSyncTime = System.currentTimeMillis()

                _syncProgress.value = _syncProgress.value.copy(
                    isSyncing = false,
                    isJustCompleted = true,
                    itemsFetchedInSync = finalItemsTotal,
                    progressPercentage = finalPct,
                    hasPendingBackfill = false
                )

                onBatchReceived?.invoke()

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
}
