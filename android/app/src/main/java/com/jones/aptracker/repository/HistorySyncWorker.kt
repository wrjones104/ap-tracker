package com.jones.aptracker.repository

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.TokenManager
import retrofit2.HttpException

class HistorySyncWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    companion object {
        private const val MAX_RETRY_ATTEMPTS = 3
    }

    override suspend fun doWork(): Result {
        // Retrying cannot conjure a token, so bail out as success rather than burning
        // the retry budget on requests that can only 401. See #308.
        if (TokenManager(applicationContext).getToken() == null) {
            Log.d("HistorySyncWorker", "No auth token; skipping background sync.")
            return Result.success()
        }

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
            com.jones.aptracker.widget.MilestonesWidgetUpdater.refreshDataAndUpdate(applicationContext, trackedRooms)

            Log.d("HistorySyncWorker", "Background HistorySyncWorker completed successfully.")
            Result.success()
        } catch (e: Exception) {
            Log.e("HistorySyncWorker", "Error executing background HistorySyncWorker", e)
            when {
                // An expired or revoked token will still be expired on the next attempt.
                e is HttpException && e.code() == 401 -> {
                    Log.w("HistorySyncWorker", "Sync rejected as unauthenticated; not retrying.")
                    Result.failure()
                }
                runAttemptCount < MAX_RETRY_ATTEMPTS -> Result.retry()
                else -> Result.failure()
            }
        }
    }
}
