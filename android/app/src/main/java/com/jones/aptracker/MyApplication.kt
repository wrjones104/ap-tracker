package com.jones.aptracker

import android.app.Application
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.jones.aptracker.diagnostics.AppExitReporter
import com.jones.aptracker.diagnostics.CrashReporter
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.repository.HistorySyncWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.util.concurrent.TimeUnit

class MyApplication : Application() {

    /** Outlives every screen; for one-shot startup work that must not block onCreate. */
    private val applicationScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onCreate() {
        super.onCreate()
        // First, so that a failure in anything below is itself reportable.
        CrashReporter.init(this)
        RetrofitClient.init(this)
        NotificationHelper.createNotificationChannels(this)
        setupPeriodicHistorySync()
        reportPreviousProcessDeath()
    }

    /**
     * Reads back why the previous process died. Off the main thread because it touches
     * SharedPreferences and an ActivityManager binder call, and nothing on screen waits on it.
     */
    private fun reportPreviousProcessDeath() {
        applicationScope.launch {
            AppExitReporter.reportSinceLastLaunch(this@MyApplication)
        }
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
