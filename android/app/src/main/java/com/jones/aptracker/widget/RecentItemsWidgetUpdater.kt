package com.jones.aptracker.widget

import android.content.Context
import android.util.Log
import androidx.glance.appwidget.GlanceAppWidgetManager
import androidx.glance.appwidget.state.updateAppWidgetState
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
            // updateAll() alone is not enough: for a widget whose Glance session is still running,
            // update() only re-reads `stateDefinition` and recomposes -- it does not re-run
            // provideGlance. Bumping the token first is what makes the composition reload
            // SharedPreferences and the database instead of redrawing its cached state.
            bumpRefreshToken(context)
            RecentItemsWidget().updateAll(context)
            Log.d("WidgetUpdater", "Successfully triggered updateAll for RecentItemsWidget.")
        } catch (e: Exception) {
            Log.e("WidgetUpdater", "Failed to update RecentItemsWidget instances", e)
        }
    }

    /**
     * Marks every placed widget as needing a fresh read. Safe to call for widgets that have no
     * Glance state yet -- the store is created on demand.
     */
    suspend fun bumpRefreshToken(context: Context) {
        val glanceIds = GlanceAppWidgetManager(context).getGlanceIds(RecentItemsWidget::class.java)
        val now = System.currentTimeMillis()
        glanceIds.forEach { glanceId ->
            try {
                updateAppWidgetState(context, glanceId) { prefs ->
                    prefs[RecentItemsWidget.REFRESH_TOKEN] = now
                }
            } catch (e: Exception) {
                Log.e("WidgetUpdater", "Failed to bump refresh token for $glanceId", e)
            }
        }
    }
}
