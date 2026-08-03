package com.jones.aptracker.repository

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.network.RetrofitClient

class HistorySyncWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        Log.d("HistorySyncWorker", "Starting background HistorySyncWorker job...")
        val targetRoomId = inputData.getInt("target_room_id", -1).let { if (it == -1) null else it }

        return try {
            val db = AppDatabase.getInstance(applicationContext)
            val apiService = RetrofitClient.instance
            val repository = HistoryRepository(apiService, db.historyDao(), db.hintDao(), applicationContext)

            val trackedRooms = apiService.getUserTrackedSlots()

            repository.syncHistoryBatch(trackedRooms, priorityRoomId = targetRoomId)
            repository.refreshHintHistory(targetRoomId)

            Log.d("HistorySyncWorker", "Background HistorySyncWorker completed successfully.")
            Result.success()
        } catch (e: Exception) {
            Log.e("HistorySyncWorker", "Error executing background HistorySyncWorker", e)
            if (runAttemptCount < 3) {
                Result.retry()
            } else {
                Result.failure()
            }
        }
    }
}
