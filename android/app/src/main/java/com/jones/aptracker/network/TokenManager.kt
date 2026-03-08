package com.jones.aptracker.network

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import android.util.Log
import android.content.SharedPreferences
import java.io.File

class TokenManager(private val context: Context) {

    private val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
    private val PREFS_FILE_NAME = "secret_user_prefs"

    private val sharedPreferences: SharedPreferences by lazy {
        try {
            createEncryptedSharedPreferences()
        } catch (e: Exception) {
            Log.e("TokenManager", "Error initializing EncryptedSharedPreferences, clearing and retrying.", e)
            clearCorruptedPreferences(context, PREFS_FILE_NAME)
            try {
                createEncryptedSharedPreferences()
            } catch (retryException: Exception) {
                Log.e("TokenManager", "Failed to recreate EncryptedSharedPreferences after clearing.", retryException)
                // Fallback to empty non-encrypted or let it crash depending on requirements.
                // In this case, we'll try standard preferences as a last resort to prevent crash loop,
                // though ideally, recreate works after file deletion.
                context.getSharedPreferences(PREFS_FILE_NAME, Context.MODE_PRIVATE)
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

    private fun clearCorruptedPreferences(context: Context, prefFileName: String) {
        try {
            // Android stores shared preferences in /data/data/<package_name>/shared_prefs/<file_name>.xml
            val dir = File(context.applicationInfo.dataDir, "shared_prefs")
            val prefFile = File(dir, "$prefFileName.xml")
            if (prefFile.exists()) {
                val deleted = prefFile.delete()
                Log.d("TokenManager", "Corrupted preferences file deleted: $deleted")
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
