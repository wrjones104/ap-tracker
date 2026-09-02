package com.jones.aptracker.network

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import android.util.Log
import android.content.SharedPreferences

/**
 * Reads and writes the auth token and a few small local flags.
 *
 * Instances are cheap handles over process-wide state. Six call sites construct their
 * own `TokenManager`, so the backing store lives in the companion rather than on the
 * instance: previously the memory-only fallback was a per-instance field, which meant a
 * token saved by [AuthViewModel]'s instance was invisible to the one inside
 * [RetrofitClient]. On any device where `EncryptedSharedPreferences` failed to
 * initialize, the user could log in but every API call went out unauthenticated, was
 * rejected, and forced another logout. See #306.
 */
class TokenManager(context: Context) {

    private val appContext = context.applicationContext

    companion object {
        private const val PREFS_FILE_NAME = "secret_user_prefs"
        private const val KEY_AUTH_TOKEN = "auth_token"

        private val lock = Any()

        @Volatile
        private var sharedPreferencesInstance: SharedPreferences? = null

        /** Distinguishes "not tried yet" from "tried and fell back to memory-only". */
        @Volatile
        private var prefsInitialized = false

        /** Only used when [sharedPreferencesInstance] is null. Shared across instances. */
        @Volatile
        private var inMemoryToken: String? = null
    }

    /**
     * The encrypted store, or null if it could not be created on this device. Resolved
     * once per process; a null result is remembered so the expensive Keystore path is
     * not retried on every access.
     */
    private val prefs: SharedPreferences?
        get() {
            sharedPreferencesInstance?.let { return it }
            synchronized(lock) {
                if (!prefsInitialized) {
                    sharedPreferencesInstance = initializeSharedPreferences()
                    prefsInitialized = true
                }
                return sharedPreferencesInstance
            }
        }

    private fun initializeSharedPreferences(): SharedPreferences? {
        return try {
            createEncryptedSharedPreferences()
        } catch (e: Exception) {
            Log.e("TokenManager", "Error initializing EncryptedSharedPreferences, clearing and retrying.", e)
            clearCorruptedPreferences()
            try {
                createEncryptedSharedPreferences()
            } catch (retryException: Exception) {
                Log.e("TokenManager", "Failed to recreate EncryptedSharedPreferences. Falling back to memory-only.", retryException)
                // Returning null prevents the crash loop WITHOUT compromising security
                null
            }
        }
    }

    private fun createEncryptedSharedPreferences(): SharedPreferences {
        // Resolved here rather than at construction so a Keystore failure lands inside
        // the retry above, and so constructing a TokenManager stays cheap -- it now
        // happens on push-handling paths that run for every notification.
        val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
        return EncryptedSharedPreferences.create(
            PREFS_FILE_NAME,
            masterKeyAlias,
            appContext,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    private fun clearCorruptedPreferences() {
        try {
            if (appContext.deleteSharedPreferences(PREFS_FILE_NAME)) {
                Log.d("TokenManager", "Corrupted preferences file deleted successfully.")
            } else {
                Log.w("TokenManager", "Corrupted preferences file could not be deleted.")
            }
        } catch (e: Exception) {
            Log.e("TokenManager", "Failed to delete corrupted preferences file", e)
        }
    }

    fun saveToken(token: String) {
        val editor = prefs?.edit()
        if (editor != null) {
            editor.putString(KEY_AUTH_TOKEN, token).apply()
        } else {
            inMemoryToken = token
        }
    }

    fun getToken(): String? {
        return prefs?.getString(KEY_AUTH_TOKEN, null) ?: inMemoryToken
    }

    fun deleteToken() {
        prefs?.edit()?.remove(KEY_AUTH_TOKEN)?.apply()
        inMemoryToken = null
    }

    fun getLastSeenVersionCode(): Int {
        return prefs?.getInt("last_seen_version_code", 0) ?: 0
    }

    fun setLastSeenVersionCode(versionCode: Int) {
        prefs?.edit()?.putInt("last_seen_version_code", versionCode)?.apply()
    }

    fun isFirstLaunch(): Boolean {
        return prefs?.getBoolean("has_seen_welcome_modal", false) != true
    }

    fun setWelcomeModalSeen() {
        prefs?.edit()?.putBoolean("has_seen_welcome_modal", true)?.apply()
    }

    fun hasDismissedBadge(featureKey: String): Boolean {
        return prefs?.getBoolean("dismissed_badge_$featureKey", false) ?: false
    }

    fun dismissFeatureBadge(featureKey: String) {
        prefs?.edit()?.putBoolean("dismissed_badge_$featureKey", true)?.apply()
    }
}
