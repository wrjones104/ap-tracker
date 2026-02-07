package com.jones.aptracker

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import android.app.PendingIntent
import android.content.Intent
import androidx.core.net.toUri

class MyFirebaseMessagingService : FirebaseMessagingService() {

    override fun onMessageReceived(remoteMessage: RemoteMessage) {
        super.onMessageReceived(remoteMessage)

        remoteMessage.notification?.let { notification ->
            Log.d("FCM", "Notification Received: ${notification.title} - ${notification.body}")
            sendSystemNotification(notification.title, notification.body)
        }
    }

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        Log.d("FCM", "New token generated: $token")
    }

    private fun sendSystemNotification(title: String?, body: String?) {
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channelId = "ap_tracker_channel"

        val channel = NotificationChannel(channelId, "AP Tracker Notifications", NotificationManager.IMPORTANCE_DEFAULT)
        notificationManager.createNotificationChannel(channel)

        // Generate a unique ID for this notification
        val notificationId = System.currentTimeMillis().toInt()

        // --- CREATE ACTION INTENTS ---
        // Helper to create a PendingIntent for a specific duration
        fun createSnoozeIntent(minutes: Int): PendingIntent {
            val intent = Intent(this, SnoozeReceiver::class.java).apply {
                putExtra("DURATION_MINUTES", minutes)
                putExtra("NOTIFICATION_ID", notificationId)
                data = android.net.Uri.parse("snooze://$notificationId/$minutes")
            }
            return PendingIntent.getBroadcast(
                this,
                minutes,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
        }

        val notificationBuilder = NotificationCompat.Builder(this, channelId)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(body)
            .setAutoCancel(true)
            .addAction(android.R.drawable.ic_lock_idle_alarm, "Snooze 1h", createSnoozeIntent(60))
            .addAction(android.R.drawable.ic_lock_idle_alarm, "Snooze 8h", createSnoozeIntent(480))
            .addAction(android.R.drawable.ic_lock_idle_alarm, "Snooze 24h", createSnoozeIntent(1440))

        notificationManager.notify(notificationId, notificationBuilder.build())
    }


}