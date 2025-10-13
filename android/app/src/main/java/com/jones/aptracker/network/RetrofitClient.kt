package com.jones.aptracker.network

import okhttp3.OkHttpClient // <-- Add this import
import okhttp3.logging.HttpLoggingInterceptor // <-- Add this import
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

object RetrofitClient {
    // private const val BASE_URL = "http://192.168.1.173:5000/" // Dev
    private const val BASE_URL = "https://seedbot.net:5000/" // Prod

    val instance: ApiService by lazy {
        // Create a logging interceptor
        val logging = HttpLoggingInterceptor()
        logging.setLevel(HttpLoggingInterceptor.Level.BODY) // Log request and response bodies

        // Create an OkHttpClient and add the interceptor
        val client = OkHttpClient.Builder()
            .addInterceptor(logging)
            .build()

        val retrofit = Retrofit.Builder()
            .baseUrl(BASE_URL)
            .client(client) // <-- Add the custom client
            .addConverterFactory(GsonConverterFactory.create())
            .build()

        retrofit.create(ApiService::class.java)
    }
}