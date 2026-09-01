package com.jones.aptracker

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.app.NotificationManager
import android.util.Log
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.SnoozeRequest
import com.jones.aptracker.network.TokenManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout

class SnoozeReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val durationMinutes = intent.getIntExtra("DURATION_MINUTES", 60)
        val notificationId = intent.getIntExtra("NOTIFICATION_ID", 0)

        Log.d("SnoozeReceiver", "Action received: Snooze for $durationMinutes mins")

        // 1. Clear the notification immediately (UX)
        val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.cancel(notificationId)

        // Nothing to send without a credential -- the request would go out
        // unauthenticated and come back 401. Checked before goAsync() so there is no
        // pending result left to release. See #311.
        if (TokenManager(context).getToken().isNullOrBlank()) {
            Log.w("SnoozeReceiver", "Snooze tapped while logged out; skipping the server call.")
            return
        }

        // 2. Tell the OS "I need a few seconds to work"
        val pendingResult = goAsync()

        CoroutineScope(Dispatchers.IO).launch {
            try {
                // 3. Set a strict timeout (5 seconds) so we never hit the OS 10s kill switch
                withTimeout(5000L) {
                    val request = SnoozeRequest(duration_minutes = durationMinutes)
                    val response = RetrofitClient.instance.setGlobalSnooze(request)
                    if (response.message != null) {
                        Log.d("SnoozeReceiver", "Success: ${response.message}")
                    }
                }
            } catch (e: Exception) {
                // Log failure but DO NOT crash
                Log.e("SnoozeReceiver", "Snooze failed or timed out", e)
            } finally {
                // 4. CRITICAL: Always release the receiver, or the app will crash after 10s
                Log.d("SnoozeReceiver", "Releasing wake lock")
                pendingResult.finish()
            }
        }
    }
}