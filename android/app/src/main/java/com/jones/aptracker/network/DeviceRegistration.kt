package com.jones.aptracker.network

import android.content.Context
import android.provider.Settings
import android.util.Log
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.tasks.await
import kotlin.coroutines.cancellation.CancellationException

/**
 * Sends this device's push token to the server.
 *
 * Shared by app launch and [com.jones.aptracker.MyFirebaseMessagingService.onNewToken],
 * so a token Firebase rotates reaches the server without waiting for the next launch.
 */
object DeviceRegistration {
    private const val TAG = "DeviceRegistration"

    /** What the server answers, with 410, for a token FCM has retired (#364). */
    private const val DEAD_TOKEN_ERROR = "fcm_token_unregistered"

    /**
     * Register [token], or Firebase's current token when null. Does nothing when
     * logged out.
     *
     * A device restored from a backup or a transfer can carry the old install's
     * cached token, which FCM has already retired. The server refuses that with a
     * 410, and this deletes the token, fetches a fresh one and tries once more.
     * Once only: a token Firebase has just issued is not dead, and a second
     * refusal means something else is wrong.
     */
    suspend fun register(context: Context, token: String? = null) {
        if (TokenManager(context).getToken() == null) {
            Log.w(TAG, "User not logged in. Cannot register FCM token.")
            return
        }

        // A forced logout invalidates the FCM token on a detached coroutine. Fetching
        // before that finishes would hand the server the very token the pending delete
        // is about to destroy, leaving the device silently unreachable. Wait it out.
        SessionManager.awaitTokenInvalidation()

        val androidId = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)

        try {
            val first = token ?: FirebaseMessaging.getInstance().token.await()
            Log.d(TAG, "Sending FCM token to server...")
            val response = RetrofitClient.instance.registerDevice(RegisterDeviceRequest(first, androidId))
            if (response.isSuccessful) {
                Log.i(TAG, "FCM token and Android ID registered with backend successfully.")
                return
            }

            val body = response.errorBody()?.string()
            if (response.code() != 410 || body?.contains(DEAD_TOKEN_ERROR) != true) {
                Log.e(TAG, "Backend FCM registration failed: ${response.code()} - $body")
                return
            }

            Log.w(TAG, "Server says this FCM token is dead; fetching a fresh one.")
            val messaging = FirebaseMessaging.getInstance()
            messaging.deleteToken().await()
            val fresh = messaging.token.await()
            val retry = RetrofitClient.instance.registerDevice(RegisterDeviceRequest(fresh, androidId))
            if (retry.isSuccessful) {
                Log.i(TAG, "Fresh FCM token registered with backend.")
            } else {
                Log.e(TAG, "Fresh FCM token was refused too: ${retry.code()} - ${retry.errorBody()?.string()}")
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.e(TAG, "Error registering FCM token with the server", e)
        }
    }
}
