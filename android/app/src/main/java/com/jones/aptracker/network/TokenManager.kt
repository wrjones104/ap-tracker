package com.jones.aptracker.network

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import android.util.Log
import android.content.SharedPreferences

/**
 * How long a stashed token stays usable on the wire.
 *
 * The age check guards one direction only. Presenting a stranded token to the auth
 * callback would upgrade whichever guest account it belongs to into the Discord
 * identity being signed in, which on a shared device is somebody else's. Handing a
 * session back to its own owner carries no such risk and needs no limit.
 *
 * A day, rather than the half hour this started at. A Discord signup inside the flow
 * can include an email verification and a 2FA prompt, and half an hour failed those
 * users in the worst available way: the stash was dropped, the callback went out
 * unauthenticated, and the server created the second account this whole mechanism
 * exists to prevent.
 */
internal const val UPGRADE_TOKEN_TTL_MS = 24L * 60L * 60L * 1000L

/** What a stashed guest token may be used for. */
internal enum class UpgradeTokenState {
    /** Nothing is stashed. */
    NONE,

    /** Recent enough to present to the auth callback. */
    USABLE,

    /** Stashed but too old to send. Still its owner's session, so still restorable. */
    STALE
}

/**
 * Decides what may be done with a stashed token, from its age alone.
 *
 * Split out as a pure function because everything that went wrong here was a decision
 * rather than a mechanism: expiry used to delete the stash, and both callers read it
 * through the same getter, so a stale stash was destroyed on the way to being refused.
 * A missing timestamp counts as stale rather than usable -- it means the stash outlived
 * the write that dated it, and there is no way to tell how old it is.
 */
internal fun upgradeTokenState(hasToken: Boolean, stashedAt: Long?, now: Long): UpgradeTokenState {
    if (!hasToken) return UpgradeTokenState.NONE
    if (stashedAt == null) return UpgradeTokenState.STALE
    return if (now - stashedAt > UPGRADE_TOKEN_TTL_MS) {
        UpgradeTokenState.STALE
    } else {
        UpgradeTokenState.USABLE
    }
}

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

        /**
         * Where a guest's token waits while they are off at Discord.
         *
         * It cannot stay under [KEY_AUTH_TOKEN]: an ambient credential during the
         * OAuth round trip is what #311 was about, where a request rejected mid-flow
         * ran the full logout and cleared the local database. But the callback needs
         * it -- presenting it is what tells the server to upgrade the guest in place
         * rather than create a second account and strand their rooms (#324) -- so it
         * is set aside here and attached to that one request by hand.
         */
        private const val KEY_UPGRADE_TOKEN = "guest_upgrade_token"
        private const val KEY_UPGRADE_TOKEN_AT = "guest_upgrade_token_at"

        private val lock = Any()

        @Volatile
        private var sharedPreferencesInstance: SharedPreferences? = null

        /** Distinguishes "not tried yet" from "tried and fell back to memory-only". */
        @Volatile
        private var prefsInitialized = false

        /** Only used when [sharedPreferencesInstance] is null. Shared across instances. */
        @Volatile
        private var inMemoryToken: String? = null

        /** The same fallback, for the token set aside during a guest upgrade. */
        @Volatile
        private var inMemoryUpgradeToken: String? = null

        @Volatile
        private var inMemoryUpgradeTokenAt: Long? = null
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

    /**
     * Moves the current token out of the way for the duration of a guest upgrade.
     *
     * After this, [getToken] returns null -- so nothing sends it by accident -- while
     * [getUpgradeToken] can still hand it to the auth callback.
     */
    fun stashTokenForUpgrade() {
        val token = getToken() ?: return
        val now = System.currentTimeMillis()
        val editor = prefs?.edit()
        if (editor != null) {
            editor.putString(KEY_UPGRADE_TOKEN, token)
                .putLong(KEY_UPGRADE_TOKEN_AT, now)
                .apply()
        } else {
            inMemoryUpgradeToken = token
            inMemoryUpgradeTokenAt = now
        }
        deleteToken()
    }

    private fun readStashedToken(): String? {
        return prefs?.getString(KEY_UPGRADE_TOKEN, null) ?: inMemoryUpgradeToken
    }

    private fun readStashedAt(): Long? {
        return prefs?.getLong(KEY_UPGRADE_TOKEN_AT, 0L)?.takeIf { it != 0L }
            ?: inMemoryUpgradeTokenAt
    }

    private fun stashState(): UpgradeTokenState =
        upgradeTokenState(readStashedToken() != null, readStashedAt(), System.currentTimeMillis())

    /** Whether anything is stashed, at any age. */
    fun hasStashedToken(): Boolean = stashState() != UpgradeTokenState.NONE

    /** Whether something is stashed but too old to present to the auth callback. */
    fun hasStaleStashedToken(): Boolean = stashState() == UpgradeTokenState.STALE

    /**
     * The stashed token, if it is recent enough to send.
     *
     * Refusing and deleting are different things, and this used to do both. A stash
     * too old to present is still the only handle on the account it belongs to, so it
     * stays exactly where it is; [hasStaleStashedToken] is how a caller notices, and
     * [restoreStashedToken] is how the user gets it back.
     */
    fun getUpgradeToken(): String? {
        val token = readStashedToken() ?: return null
        if (stashState() != UpgradeTokenState.USABLE) {
            Log.w("TokenManager", "Guest upgrade token is stale; not presenting it.")
            return null
        }
        return token
    }

    /**
     * Puts the stashed token back, for an upgrade that was cancelled or failed.
     *
     * Deliberately ignores the age check that [getUpgradeToken] applies. Handing a
     * user back their own session is safe at any age, and dropping it because the
     * upgrade took a while is the account loss this whole mechanism exists to stop.
     */
    fun restoreStashedToken(): Boolean {
        val token = readStashedToken() ?: return false
        saveToken(token)
        clearStashedToken()
        return true
    }

    fun clearStashedToken() {
        prefs?.edit()?.remove(KEY_UPGRADE_TOKEN)?.remove(KEY_UPGRADE_TOKEN_AT)?.apply()
        inMemoryUpgradeToken = null
        inMemoryUpgradeTokenAt = null
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
