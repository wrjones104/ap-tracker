package com.jones.aptracker.network

import android.content.Context
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/**
 * Sends a token Firebase rotated to the server, from work that outlives the push service.
 *
 * onNewToken used to launch the registration on the service's own scope, and the service can
 * stop as soon as onNewToken returns. A rotation while the app was in the background could
 * then be lost with the process, leaving the server pushing to a dead token until the next
 * launch (#392).
 */
class DeviceRegistrationWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    companion object {
        private const val TAG = "DeviceRegistrationWorker"
        private const val WORK_NAME = "fcm_token_registration"
        private const val MAX_ATTEMPTS = 5

        /**
         * Queues a registration. Several rotations collapse into one job, and the job sends
         * whatever token Firebase holds when it runs, so a replaced job loses nothing.
         */
        fun enqueue(context: Context) {
            val request = OneTimeWorkRequestBuilder<DeviceRegistrationWorker>()
                .setConstraints(
                    Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
                )
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(context)
                .enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.REPLACE, request)
        }
    }

    override suspend fun doWork(): Result {
        Log.d(TAG, "Registering the current FCM token (attempt ${runAttemptCount + 1}).")
        if (DeviceRegistration.register(applicationContext)) return Result.success()
        return if (runAttemptCount + 1 < MAX_ATTEMPTS) Result.retry() else Result.failure()
    }
}
