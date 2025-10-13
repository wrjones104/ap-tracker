package com.jones.aptracker.network

import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

// This object provides a single, configured instance of our ApiService
object RetrofitClient {

    // IMPORTANT: Replace with the IP address of the computer running your Python script.
    // Use your computer's local network IP (e.g., 192.168.1.100), not "localhost" or "127.0.0.1".
    private const val BASE_URL = "http://192.168.1.172:5000/"

    val instance: ApiService by lazy {
        val retrofit = Retrofit.Builder()
            .baseUrl(BASE_URL)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
        retrofit.create(ApiService::class.java)
    }
}