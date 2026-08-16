package com.jones.aptracker.repository

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.jones.aptracker.network.RetrofitClient

class HistorySyncWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    companion object {
        private const val MAX_RETRY_ATTEMPTS = 3
    }

    override suspend fun doWork(): Result {
        if (HistorySyncManager.shouldSkipWorker()) {
            Log.d("HistorySyncWorker", "Skipping background worker execution (active sync in progress or sync completed recently).")
            return Result.success()
        }

        Log.d("HistorySyncWorker", "Starting background HistorySyncWorker job...")
        val targetRoomId = inputData.getInt("target_room_id", -1).let { if (it == -1) null else it }

        return try {
            val repository = HistoryRepository.getInstance(applicationContext)
            val apiService = RetrofitClient.instance

            val trackedRooms = apiService.getUserTrackedSlots()

            repository.syncHistoryBatch(trackedRooms, priorityRoomId = targetRoomId)
            repository.refreshHintHistory(targetRoomId)

            com.jones.aptracker.widget.RecentItemsWidgetUpdater.update(applicationContext)

            Log.d("HistorySyncWorker", "Background HistorySyncWorker completed successfully.")
            Result.success()
        } catch (e: Exception) {
            Log.e("HistorySyncWorker", "Error executing background HistorySyncWorker", e)
            if (runAttemptCount < MAX_RETRY_ATTEMPTS) {
                Result.retry()
            } else {
                Result.failure()
            }
        }
    }
}
