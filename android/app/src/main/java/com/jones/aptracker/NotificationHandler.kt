package com.jones.aptracker

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.provider.Settings
import android.util.Log
import android.widget.Toast
import androidx.core.app.NotificationCompat
import androidx.core.net.toUri
import com.google.gson.JsonParser
import com.jones.aptracker.network.RegisterDeviceRequest
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.TokenManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import org.json.JSONObject
import org.json.JSONStringer
import org.unifiedpush.android.connector.FailedReason
import org.unifiedpush.android.connector.PushService
import org.unifiedpush.android.connector.UnifiedPush
import org.unifiedpush.android.connector.data.PushEndpoint
import org.unifiedpush.android.connector.data.PushMessage

class NotificationHandler : PushService() {

    override fun onMessage(message: PushMessage, instance: String) {
        try {
            val json = JSONObject(String(message.content, Charsets.UTF_8))

            val title = json.optString("title")
            val body = json.optString("body")

            val data = json.optJSONObject("data")
            val bundledItems = data?.optString("bundled_items")
            val bundleType = data?.optString("bundle_type")

            sendSystemNotification(title, body, bundledItems, bundleType)
        } catch (e: Exception) {
            Log.e("NotificationHandler", "Error parsing push message", e)
        }
    }

    private fun sendSystemNotification(title: String?, body: String?, bundledItems: String?, bundleType: String?) {
        val notificationManager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        val channelId = "ap_tracker_channel"

        val channel = NotificationChannel(
            channelId,
            "AP Tracker Notifications",
            NotificationManager.IMPORTANCE_DEFAULT
        )
        notificationManager.createNotificationChannel(channel)

        // Generate a unique ID for this notification
        val notificationId = System.currentTimeMillis().toInt()

        // --- 1. CREATE MAIN ACTIVITY INTENT ---
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
            notificationId,
            intent,
            PendingIntent.FLAG_ONE_SHOT or PendingIntent.FLAG_IMMUTABLE
        )

        // --- 2. CREATE SNOOZE ACTIONS ---
        fun createSnoozeIntent(minutes: Int): PendingIntent {
            val snoozeIntent = Intent(this, SnoozeReceiver::class.java).apply {
                putExtra("DURATION_MINUTES", minutes)
                putExtra("NOTIFICATION_ID", notificationId)
                data = "snooze://$notificationId/$minutes".toUri()
            }
            return PendingIntent.getBroadcast(
                this,
                minutes,
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

    override fun onNewEndpoint(endpoint: PushEndpoint, instance: String) {
        Log.d("NotificationHandler", "New UnifiedPush endpoint: ${endpoint.url}")
        TokenManager(this).saveEndpoint(Json.encodeToString(endpoint))
        
        val androidId = Settings.Secure.getString(
            contentResolver,
            Settings.Secure.ANDROID_ID
        )

        CoroutineScope(Dispatchers.IO).launch {
            try {
                val request = RegisterDeviceRequest(
                    endpoint = endpoint.url,
                    key_auth = endpoint.pubKeySet?.auth,
                    key_pub = endpoint.pubKeySet?.pubKey,
                    android_id = androidId
                )
                val response = RetrofitClient.instance.registerDevice(request)
                if (response.isSuccessful) {
                    Log.i("NotificationHandler", "Successfully registered UnifiedPush endpoint with backend")
                } else {
                    Log.e("NotificationHandler", "Failed to register UnifiedPush endpoint: ${response.code()}")
                }
            } catch (e: Exception) {
                Log.e("NotificationHandler", "Error registering UnifiedPush endpoint", e)
            }
        }
    }

    override fun onRegistrationFailed(reason: FailedReason, instance: String) {
        if (reason == FailedReason.VAPID_REQUIRED) {
            CoroutineScope(Dispatchers.IO).launch {
                try {
                    val vapidKey = RetrofitClient.instance.getVapidKey().public_key
                    withContext(Dispatchers.Main) {
                        UnifiedPush.register(this@NotificationHandler, instance, vapid = vapidKey)
                    }
                } catch (e: Exception) {
                    Log.e("NotificationHandler", "Failed to get VAPID key from server", e)
                }
            }
        } else {
            Toast.makeText(this, "Registration Failed: $reason", Toast.LENGTH_SHORT).show()
            UnifiedPush.removeDistributor(this)
        }
    }

    override fun onUnregistered(instance: String) {
        Log.d("NotificationHandler", "UnifiedPush instance unregistered: $instance")

        val tokenManager = TokenManager(this)
        val endpoint = tokenManager.getEndpoint()
        if (tokenManager.getToken() != null && endpoint != null) {
            CoroutineScope(Dispatchers.IO).launch {
                try {
                    val request = RegisterDeviceRequest(endpoint = endpoint)
                    RetrofitClient.instance.unregisterDevice(request)
                    Log.i("NotificationHandler", "Successfully notified backend of unregistration")
                } catch (e: Exception) {
                    Log.e("NotificationHandler", "Error notifying backend of unregistration", e)
                }
            }
        }
    }
}
