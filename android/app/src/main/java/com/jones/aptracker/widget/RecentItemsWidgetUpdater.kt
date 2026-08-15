package com.jones.aptracker.widget

import android.content.Context
import android.util.Log
import androidx.glance.appwidget.updateAll
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

object RecentItemsWidgetUpdater {
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    fun updateAsync(context: Context) {
        scope.launch {
            update(context)
        }
    }

    suspend fun update(context: Context) {
        try {
            RecentItemsWidget().updateAll(context)
            Log.d("WidgetUpdater", "Successfully triggered updateAll for RecentItemsWidget.")
        } catch (e: Exception) {
            Log.e("WidgetUpdater", "Failed to update RecentItemsWidget instances", e)
        }
    }
}
