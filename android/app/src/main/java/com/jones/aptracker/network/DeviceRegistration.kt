package com.jones.aptracker.network

import android.content.Context
import android.provider.Settings
import android.util.Log
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.tasks.await
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.cancellation.CancellationException

/**
 * Sends this device's push token to the server.
 *
 * Shared by app launch and [DeviceRegistrationWorker], which onNewToken queues, so a
 * token Firebase rotates reaches the server without waiting for the next launch.
 */
object DeviceRegistration {
    private const val TAG = "DeviceRegistration"

    /** What the server answers, with 410, for a token FCM has retired (#364). */
    private const val DEAD_TOKEN_ERROR = "fcm_token_unregistered"

    // Launch, a recomposition after rotation and onNewToken can all land at once. Run them
    // one at a time so one call's deleteToken cannot destroy the token another is sending.
    private val mutex = Mutex()

    // The server relies on at most one delete-and-refresh per launch. The refresh itself
    // fires onNewToken, which re-enters register(), so the bound must be per process, not
    // per call, or a server that wrongly 410s every token turns this into a loop.
    private val recoveryUsed = AtomicBoolean(false)

    /**
     * Register Firebase's current token. Does nothing when logged out.
     *
     * A device restored from a backup or a transfer can carry the old install's
     * cached token, which FCM has already retired. The server refuses that with a
     * 410, and this deletes the token, fetches a fresh one and tries once more.
     * Once per process: a token Firebase has just issued is not dead, and a second
     * refusal means something else is wrong.
     *
     * The lock cannot deadlock on the refresh: Firebase delivers the onNewToken that
     * fetching the fresh token causes on its own thread, and nothing here waits for it.
     * That onNewToken queues a [DeviceRegistrationWorker] with REPLACE. If this call is
     * itself running in that worker, it is cancelled, and the replacement sends the
     * fresh token; otherwise the worker re-sends it, which the server treats as a no-op.
     *
     * Returns false only when trying again later could help: no network, a timeout, a
     * 408/429 or a server error. Everything else, including a refusal, counts as settled.
     */
    suspend fun register(context: Context): Boolean = mutex.withLock {
        if (TokenManager(context).getToken() == null) {
            Log.w(TAG, "User not logged in. Cannot register FCM token.")
            return@withLock true
        }

        // A forced logout invalidates the FCM token on a detached coroutine. Fetching
        // before that finishes would hand the server the very token the pending delete
        // is about to destroy, leaving the device silently unreachable. Wait it out.
        SessionManager.awaitTokenInvalidation()

        val androidId = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)

        var recovering = false
        try {
            val first = FirebaseMessaging.getInstance().token.await()
            Log.d(TAG, "Sending FCM token to server...")
            val response = RetrofitClient.instance.registerDevice(RegisterDeviceRequest(first, androidId))
            if (response.isSuccessful) {
                Log.i(TAG, "FCM token and Android ID registered with backend successfully.")
                return@withLock true
            }

            val body = response.errorBody()?.string()
            if (response.code() != 410 || body?.contains(DEAD_TOKEN_ERROR) != true) {
                Log.e(TAG, "Backend FCM registration failed: ${response.code()} - $body")
                return@withLock !isRetryable(response.code())
            }

            if (!recoveryUsed.compareAndSet(false, true)) {
                Log.e(TAG, "Server refused this FCM token too; not refreshing again this launch.")
                return@withLock true
            }

            recovering = true
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
            !isRetryable(retry.code())
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // A network or Play Services failure part-way through the refresh must not
            // spend the once-per-process recovery: the retry would meet the same 410 and
            // give up as settled, leaving the dead token on the server.
            if (recovering) recoveryUsed.set(false)
            Log.e(TAG, "Error registering FCM token with the server", e)
            false
        }
    }

    /** Server errors, plus the two 4xx a proxy may send for a request worth repeating. */
    private fun isRetryable(code: Int): Boolean = code >= 500 || code == 408 || code == 429
}