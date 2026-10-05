package com.jones.aptracker.network

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import android.util.Log
import android.content.SharedPreferences

class PasswordManager(private val context: Context) {

    private val PREFS_FILE_NAME = "ap_passwords"

    private val sharedPreferences: SharedPreferences? by lazy {
        initializeSharedPreferences()
    }

    /**
     * Opens the store, deleting and recreating it once if it cannot be read. A file restored
     * from a backup (#396) holds keysets sealed by another install's Keystore key, so its
     * passwords are unrecoverable anyway; without the retry the store stays dead for the
     * life of the install and every save is silently dropped.
     */
    private fun initializeSharedPreferences(): SharedPreferences? {
        return try {
            createEncryptedSharedPreferences()
        } catch (e: Exception) {
            Log.e("PasswordManager", "Error initializing EncryptedSharedPreferences, clearing and retrying.", e)
            clearCorruptedPreferences()
            try {
                createEncryptedSharedPreferences()
            } catch (retryException: Exception) {
                Log.e("PasswordManager", "Failed to recreate EncryptedSharedPreferences.", retryException)
                null
            }
        }
    }

    private fun createEncryptedSharedPreferences(): SharedPreferences {
        val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
        return EncryptedSharedPreferences.create(
            PREFS_FILE_NAME,
            masterKeyAlias,
            context,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    private fun clearCorruptedPreferences() {
        try {
            if (!context.deleteSharedPreferences(PREFS_FILE_NAME)) {
                Log.w("PasswordManager", "Corrupted preferences file could not be deleted.")
            }
        } catch (e: Exception) {
            Log.e("PasswordManager", "Failed to delete corrupted preferences file", e)
        }
    }

    fun savePassword(host: String, password: String) {
        sharedPreferences?.edit()?.putString(host, password)?.apply()
    }

    fun getPassword(host: String): String? {
        return sharedPreferences?.getString(host, null)
    }

    fun deletePassword(host: String) {
        sharedPreferences?.edit()?.remove(host)?.apply()
    }
}
