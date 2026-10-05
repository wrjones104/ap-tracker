package com.jones.aptracker

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.jones.aptracker.network.DeviceRegistrationWorker
import com.jones.aptracker.network.TokenManager
import com.jones.aptracker.repository.HistorySyncManager

class MyFirebaseMessagingService : FirebaseMessagingService() {

    override fun onMessageReceived(remoteMessage: RemoteMessage) {
        super.onMessageReceived(remoteMessage)
        Log.d("FCM_DEBUG", "Raw Data Payload: ${remoteMessage.data}")

        // Extract bundled items, bundle type, channel, and notification type
        val bundledItems = remoteMessage.data["bundled_items"]
        val bundleType = remoteMessage.data["bundle_type"]
        val payloadChannelId = remoteMessage.data["channel_id"]
        val notificationType = remoteMessage.data["notification_type"] ?: remoteMessage.data["type"]
        val channelId = NotificationHelper.getChannelId(payloadChannelId, notificationType)

        remoteMessage.notification?.let { notification ->
            Log.d("FCM", "Notification Received: ${notification.title} - ${notification.body} (Channel: $channelId)")
            // Pass the bundled items, bundle type, and resolved channel ID to the generator
            sendSystemNotification(notification.title, notification.body, bundledItems, bundleType, channelId)
        }

        // The sync below calls authenticated endpoints. A logged-out device keeps
        // receiving pushes until the server prunes its registration, so without this guard
        // every push fired five requests that could only ever 401. See #308.
        if (TokenManager(applicationContext).getToken() == null) {
            Log.w("FCM", "Push received while logged out; skipping history sync.")
            return
        }

        // One in-process sync, with a WorkManager job behind it in case the process dies. These
        // used to run as two independent syncs, each with a full hint download (#411).
        HistorySyncManager.syncForPush(applicationContext)
    }

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        Log.d("FCM", "New token generated.")
        // Only logged before, so a token Firebase rotated reached the server at the
        // next launch at the earliest, and pushes went nowhere until then (#364). As work,
        // not a launch on this service's scope, so it survives the service stopping and
        // retries when offline (#392).
        DeviceRegistrationWorker.enqueue(applicationContext)
    }

    private fun sendSystemNotification(
        title: String?,
        body: String?,
        bundledItems: String?,
        bundleType: String?,
        channelId: String
    ) {
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        // Generate a unique ID for this notification
        val notificationId = System.currentTimeMillis().toInt()

        // --- 1. CREATE MAIN ACTIVITY INTENT ---
        // This makes the notification clickable and passes the data to the app
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
            if (bundledItems != null) {
                putExtra("bundled_items", bundledItems)
            }
            if (bundleType != null) {
                putExtra("bundle_type", bundleType)
            }
        }

        val pendingIntent = PendingIntent.getActivity(
            this,
            notificationId, // Use ID to ensure uniqueness if needed
            intent,
            PendingIntent.FLAG_ONE_SHOT or PendingIntent.FLAG_IMMUTABLE
        )

        // --- 2. CREATE SNOOZE ACTIONS ---
        fun createSnoozeIntent(minutes: Int): PendingIntent {
            val snoozeIntent = Intent(this, SnoozeReceiver::class.java).apply {
                putExtra("DURATION_MINUTES", minutes)
                putExtra("NOTIFICATION_ID", notificationId)
                data = android.net.Uri.parse("snooze://$notificationId/$minutes")
            }
            return PendingIntent.getBroadcast(
                this,
                minutes, // Request code
                snoozeIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
        }

        val notificationBuilder = NotificationCompat.Builder(this, channelId)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(body)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .addAction(android.R.drawable.ic_lock_idle_alarm, "Snooze 1h", createSnoozeIntent(60))
            .addAction(android.R.drawable.ic_lock_idle_alarm, "Snooze 8h", createSnoozeIntent(480))
            .addAction(android.R.drawable.ic_lock_idle_alarm, "Snooze 24h", createSnoozeIntent(1440))

        notificationManager.notify(notificationId, notificationBuilder.build())
    }

    companion object {
        fun sendLocalNotification(
            context: Context,
            title: String,
            body: String,
            channelId: String = NotificationHelper.CHANNEL_GENERAL
        ) {
            val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

            val notificationId = System.currentTimeMillis().toInt()
            
            val intent = Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
            }

            val pendingIntent = PendingIntent.getActivity(
                context,
                notificationId,
                intent,
                PendingIntent.FLAG_ONE_SHOT or PendingIntent.FLAG_IMMUTABLE
            )

            val notificationBuilder = NotificationCompat.Builder(context, channelId)
                .setSmallIcon(R.drawable.ic_launcher_foreground)
                .setContentTitle(title)
                .setContentText(body)
                .setAutoCancel(true)
                .setContentIntent(pendingIntent)

            notificationManager.notify(notificationId, notificationBuilder.build())
        }
    }
}