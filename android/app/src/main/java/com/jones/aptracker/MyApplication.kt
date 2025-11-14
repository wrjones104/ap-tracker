package com.jones.aptracker

import android.app.Application
import com.jones.aptracker.network.RetrofitClient

class MyApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        RetrofitClient.init(this)
    }
}