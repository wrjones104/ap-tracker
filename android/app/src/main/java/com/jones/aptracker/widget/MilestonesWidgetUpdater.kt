package com.jones.aptracker.widget

import android.content.Context
import android.util.Log
import androidx.glance.appwidget.GlanceAppWidgetManager
import androidx.glance.appwidget.state.updateAppWidgetState
import androidx.glance.appwidget.updateAll
import com.jones.aptracker.network.RoomWithTrackedSlots
import com.jones.aptracker.repository.MilestonesRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

object MilestonesWidgetUpdater {
    private const val TAG = "MilestonesWidgetUpdater"

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
            // its configuration and the milestone cache instead of redrawing cached state.
            bumpRefreshToken(context)
            MilestonesWidget().updateAll(context)
            Log.d(TAG, "Successfully triggered updateAll for MilestonesWidget.")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to update MilestonesWidget instances", e)
        }
    }

    /**
     * Refreshes the local milestone cache from the network, then redraws the widget.
     *
     * Call this from sync paths instead of [update] alone: the widget itself reads only local data
     * now, so without a cache refresh it would happily redraw stale milestones. Pass [trackedRooms]
     * when the caller already fetched the roster, which every sync path has.
     *
     * No-ops when no Milestones widget is placed, so accounts without the widget pay nothing.
     */
    suspend fun refreshDataAndUpdate(
        context: Context,
        trackedRooms: List<RoomWithTrackedSlots>? = null
    ) {
        try {
            if (!hasPlacedWidgets(context)) return
            MilestonesRepository.refreshCache(context, trackedRooms)
            update(context)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to refresh milestone data for widgets", e)
        }
    }

    fun refreshDataAndUpdateAsync(
        context: Context,
        trackedRooms: List<RoomWithTrackedSlots>? = null
    ) {
        val appContext = context.applicationContext
        scope.launch {
            refreshDataAndUpdate(appContext, trackedRooms)
        }
    }

    /**
     * Refreshes one slot's milestone definitions, then redraws. Used after the user adds, edits, or
     * deletes a milestone group, where a full roster refresh would be wasteful.
     */
    fun refreshSlotAndUpdateAsync(context: Context, roomDbId: Int, slotId: Int) {
        val appContext = context.applicationContext
        scope.launch {
            try {
                if (hasPlacedWidgets(appContext)) {
                    MilestonesRepository.refreshSlot(appContext, roomDbId, slotId)
                }
                update(appContext)
            } catch (e: Exception) {
                Log.e(TAG, "Failed to refresh milestones for room $roomDbId slot $slotId", e)
            }
        }
    }

    /**
     * Refreshes the cache only if it has gone stale, then redraws. Used right after widget
     * configuration so a widget placed on a cold app still fills in without waiting for a sync.
     */
    fun refreshIfStaleAndUpdateAsync(context: Context) {
        val appContext = context.applicationContext
        scope.launch {
            try {
                if (MilestonesRepository.refreshCacheIfStale(appContext)) {
                    update(appContext)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to warm milestone cache", e)
            }
        }
    }

    private suspend fun hasPlacedWidgets(context: Context): Boolean =
        GlanceAppWidgetManager(context).getGlanceIds(MilestonesWidget::class.java).isNotEmpty()

    /**
     * Marks every placed widget as needing a fresh read.
     */
    suspend fun bumpRefreshToken(context: Context) {
        val glanceIds = GlanceAppWidgetManager(context).getGlanceIds(MilestonesWidget::class.java)
        val now = System.currentTimeMillis()
        glanceIds.forEach { glanceId ->
            try {
                updateAppWidgetState(context, glanceId) { prefs ->
                    prefs[MilestonesWidget.REFRESH_TOKEN] = now
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to bump refresh token for $glanceId", e)
            }
        }
    }
}
