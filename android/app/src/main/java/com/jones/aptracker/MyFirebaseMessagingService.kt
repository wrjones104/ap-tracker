package com.jones.aptracker

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class MyFirebaseMessagingService : FirebaseMessagingService() {

    // This function is called when a new notification arrives while the app is in the background
    override fun onMessageReceived(remoteMessage: RemoteMessage) {
        super.onMessageReceived(remoteMessage)

        remoteMessage.notification?.let { notification ->
            Log.d("FCM", "Notification Received: ${notification.title} - ${notification.body}")
            sendSystemNotification(notification.title, notification.body)
        }
    }

    // This function is called when FCM issues a new token
    override fun onNewToken(token: String) {
        super.onNewToken(token)
        Log.d("FCM", "New token generated: $token")
        // You would send this new token to your server here
        // sendTokenToServer(token)
    }

    private fun sendSystemNotification(title: String?, body: String?) {
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channelId = "ap_tracker_channel"

        // On modern Android versions, you need to create a Notification Channel
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(channelId, "AP Tracker Notifications", NotificationManager.IMPORTANCE_DEFAULT)
            notificationManager.createNotificationChannel(channel)
        }

        val notificationBuilder = NotificationCompat.Builder(this, channelId)
            .setSmallIcon(R.drawable.ic_launcher_foreground) // Default app icon
            .setContentTitle(title)
            .setContentText(body)
            .setAutoCancel(true)

        // The ID should be unique for each notification to show multiple at once
        notificationManager.notify(System.currentTimeMillis().toInt(), notificationBuilder.build())
    }
}