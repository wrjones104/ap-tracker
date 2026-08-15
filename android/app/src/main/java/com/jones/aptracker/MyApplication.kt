package com.jones.aptracker

import android.app.Application
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.repository.HistorySyncWorker
import java.util.concurrent.TimeUnit

class MyApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        RetrofitClient.init(this)
        NotificationHelper.createNotificationChannels(this)
        setupPeriodicHistorySync()
    }

    private fun setupPeriodicHistorySync() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        val periodicSyncRequest = PeriodicWorkRequestBuilder<HistorySyncWorker>(
            15, TimeUnit.MINUTES,
            5, TimeUnit.MINUTES
        )
            .setConstraints(constraints)
            .build()

        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "PERIODIC_HISTORY_SYNC",
            ExistingPeriodicWorkPolicy.UPDATE,
            periodicSyncRequest
        )
    }
}