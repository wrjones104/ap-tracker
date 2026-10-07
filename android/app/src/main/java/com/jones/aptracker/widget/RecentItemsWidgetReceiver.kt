package com.jones.aptracker.widget

import android.content.Context
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver

class RecentItemsWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = RecentItemsWidget()

    /** First Recent Items widget placed: start the timer that keeps its "Xm ago" labels current. */
    override fun onEnabled(context: Context) {
        super.onEnabled(context)
        WidgetRedrawWorker.schedule(context)
    }

    /** Last one removed: nothing left to redraw. */
    override fun onDisabled(context: Context) {
        super.onDisabled(context)
        WidgetRedrawWorker.cancel(context)
    }
}
