package com.jones.aptracker.widget

import android.content.Context
import android.util.Log
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.jones.aptracker.repository.MilestonesRepository

/**
 * The Milestones widget's refresh button, run as work rather than inside the tap.
 *
 * Glance holds the broadcast open until its ActionCallback returns, and a foreground broadcast
 * has 10 seconds. A full refresh fans out one request per tracked slot, so on a slow network it
 * ran past that and the app ANR'd (#397).
 */
class MilestonesRefreshWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    companion object {
        private const val TAG = "MilestonesRefreshWorker"
        private const val WORK_NAME = "milestones_widget_refresh"

        /** Queues one refresh; a tap while one is pending or running is dropped. */
        fun enqueue(context: Context) {
            val request = OneTimeWorkRequestBuilder<MilestonesRefreshWorker>()
                .setConstraints(
                    Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
                )
                .build()
            WorkManager.getInstance(context)
                .enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.KEEP, request)
        }
    }

    override suspend fun doWork(): Result {
        Log.d(TAG, "Refreshing milestone cache for the widget.")
        // Neither call throws: a failed fetch keeps the previous cache, which is redrawn as is.
        MilestonesRepository.refreshCache(applicationContext)
        MilestonesWidgetUpdater.update(applicationContext)
        return Result.success()
    }
}
