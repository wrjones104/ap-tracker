package com.jones.aptracker.network

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import android.util.Log
import android.content.SharedPreferences

class TokenManager(private val context: Context) {

    private val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
    private val PREFS_FILE_NAME = "secret_user_prefs"

    private val sharedPreferences: SharedPreferences by lazy {
        initializeSharedPreferences()
    }

    private fun initializeSharedPreferences(): SharedPreferences {
        return try {
            createEncryptedSharedPreferences()
        } catch (e: Exception) {
            Log.e("TokenManager", "Error initializing EncryptedSharedPreferences, clearing and retrying.", e)
            clearCorruptedPreferences()
            try {
                createEncryptedSharedPreferences()
            } catch (retryException: Exception) {
                Log.e("TokenManager", "Failed to recreate EncryptedSharedPreferences after clearing.", retryException)
                throw RuntimeException("Could not initialize secure storage", retryException)
            }
        }
    }

    private fun createEncryptedSharedPreferences(): SharedPreferences {
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
            if (context.deleteSharedPreferences(PREFS_FILE_NAME)) {
                Log.d("TokenManager", "Corrupted preferences file deleted successfully.")
            } else {
                Log.w("TokenManager", "Corrupted preferences file could not be deleted (it may not have existed).")
            }
        } catch (e: Exception) {
            Log.e("TokenManager", "Failed to delete corrupted preferences file", e)
        }
    }

    fun saveToken(token: String) {
        sharedPreferences.edit().putString("auth_token", token).apply()
    }

    fun getToken(): String? {
        return sharedPreferences.getString("auth_token", null)
    }

    fun deleteToken() {
        sharedPreferences.edit().remove("auth_token").apply()
    }
}
