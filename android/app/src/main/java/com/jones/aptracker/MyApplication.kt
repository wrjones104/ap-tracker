package com.jones.aptracker

import android.app.Application
import com.jones.aptracker.network.RetrofitClient

class MyApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        // Initialize the RetrofitClient as soon as the app starts
        RetrofitClient.init(this)
    }
}