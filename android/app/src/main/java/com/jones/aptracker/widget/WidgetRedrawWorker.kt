package com.jones.aptracker.widget

import android.content.Context
import android.util.Log
import androidx.glance.appwidget.GlanceAppWidgetManager
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/**
 * Redraws the Recent Items widget so its "just now" / "Xm ago" labels move forward.
 *
 * The labels are worked out when the widget draws, and the widget has no timer of its own
 * (`updatePeriodMillis="0"`). The 15-minute background sync used to redraw it as a side
 * effect; once that sync moved to every 3 hours (#415), "just now" could stay on screen for
 * hours. This does the redraw alone: no network, so the server load #415 removed stays gone.
 *
 * Scheduled only while a Recent Items widget is placed, so phones without one never wake for it.
 */
class WidgetRedrawWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    companion object {
        private const val TAG = "WidgetRedrawWorker"
        private const val WORK_NAME = "PERIODIC_WIDGET_REDRAW"

        /**
         * Schedules the redraw when a Recent Items widget is placed and cancels it when none is.
         * Called on every app start, which covers widgets placed before this worker existed.
         */
        suspend fun syncSchedule(context: Context) {
            val placed = try {
                GlanceAppWidgetManager(context).getGlanceIds(RecentItemsWidget::class.java).isNotEmpty()
            } catch (e: Exception) {
                Log.w(TAG, "Could not list placed widgets; leaving the schedule as it is", e)
                return
            }
            if (placed) schedule(context) else cancel(context)
        }

        /** KEEP: an app start must not push back a redraw that is already due. */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<WidgetRedrawWorker>(15, TimeUnit.MINUTES).build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(WORK_NAME, ExistingPeriodicWorkPolicy.KEEP, request)
        }

        fun cancel(context: Context) {
            WorkManager.getInstance(context).cancelUniqueWork(WORK_NAME)
        }
    }

    override suspend fun doWork(): Result {
        // Never throws: a failed redraw is logged by the updater and simply waits for the next run.
        RecentItemsWidgetUpdater.update(applicationContext)
        return Result.success()
    }
}
