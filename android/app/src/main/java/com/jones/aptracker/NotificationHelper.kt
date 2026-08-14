package com.jones.aptracker

import android.app.NotificationChannel
import android.app.NotificationChannelGroup
import android.app.NotificationManager
import android.content.Context
import android.os.Build

object NotificationHelper {

    const val GROUP_ALERTS = "group_archipelago_alerts"

    const val CHANNEL_PROGRESSION = "channel_progression"
    const val CHANNEL_NON_PROGRESSION = "channel_non_progression"
    const val CHANNEL_HINTS = "channel_hints"
    const val CHANNEL_GENERAL = "channel_general"

    private const val LEGACY_CHANNEL_ID = "ap_tracker_channel"

    /**
     * Registers all Android notification channels and deletes legacy channels.
     * Safe to call multiple times (e.g. at Application startup).
     */
    fun createNotificationChannels(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

            // 1. Delete legacy channel if it exists
            try {
                notificationManager.deleteNotificationChannel(LEGACY_CHANNEL_ID)
            } catch (_: Exception) {
                // Ignore if legacy channel deletion fails or doesn't exist
            }

            // 2. Register Notification Channel Group
            val group = NotificationChannelGroup(GROUP_ALERTS, "Game & Room Alerts")
            notificationManager.createNotificationChannelGroup(group)

            // 3. Define organized channels with group assigned
            val progressionChannel = NotificationChannel(
                CHANNEL_PROGRESSION,
                "Progression Items",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                this.group = GROUP_ALERTS
                description = "Notifications for key progression items and goal milestones."
                enableVibration(true)
            }

            val nonProgressionChannel = NotificationChannel(
                CHANNEL_NON_PROGRESSION,
                "Non-Progression Items",
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply {
                this.group = GROUP_ALERTS
                description = "Notifications for useful items, traps, and filler items."
            }

            val hintsChannel = NotificationChannel(
                CHANNEL_HINTS,
                "Hints",
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply {
                this.group = GROUP_ALERTS
                description = "Notifications for discovered hints and location scout hints."
            }

            val generalChannel = NotificationChannel(
                CHANNEL_GENERAL,
                "General & System",
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply {
                this.group = GROUP_ALERTS
                description = "Room activity, slot completions, test notifications, and general announcements."
            }

            notificationManager.createNotificationChannels(
                listOf(
                    progressionChannel,
                    nonProgressionChannel,
                    hintsChannel,
                    generalChannel
                )
            )
        }
    }

    /**
     * Maps an incoming notification type / payload channel to a valid Notification Channel ID.
     */
    fun getChannelId(payloadChannelId: String?, notificationType: String?): String {
        if (!payloadChannelId.isNullOrBlank()) {
            when (payloadChannelId) {
                CHANNEL_PROGRESSION,
                CHANNEL_NON_PROGRESSION,
                CHANNEL_HINTS,
                CHANNEL_GENERAL -> return payloadChannelId
            }
        }

        return when (notificationType) {
            "item_progression", "item_milestone" -> CHANNEL_PROGRESSION
            "item_useful", "item_trap", "item_filler" -> CHANNEL_NON_PROGRESSION
            "hint" -> CHANNEL_HINTS
            else -> CHANNEL_GENERAL
        }
    }
}
