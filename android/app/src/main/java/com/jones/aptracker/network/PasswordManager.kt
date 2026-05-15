package com.jones.aptracker.network

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import android.util.Log
import android.content.SharedPreferences

class PasswordManager(private val context: Context) {

    private val masterKeyAlias by lazy { MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC) }
    private val PREFS_FILE_NAME = "ap_passwords"

    private val sharedPreferences: SharedPreferences? by lazy {
        initializeSharedPreferences()
    }

    private fun initializeSharedPreferences(): SharedPreferences? {
        return try {
            EncryptedSharedPreferences.create(
                PREFS_FILE_NAME,
                masterKeyAlias,
                context,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            )
        } catch (e: Exception) {
            Log.e("PasswordManager", "Error initializing EncryptedSharedPreferences", e)
            null
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
