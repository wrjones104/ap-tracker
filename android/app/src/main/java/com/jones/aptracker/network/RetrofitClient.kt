package com.jones.aptracker.network

import android.content.Context
import com.jones.aptracker.BuildConfig
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

object RetrofitClient {

    private lateinit var apiService: ApiService
    private lateinit var tokenManager: TokenManager

    fun init(context: Context) {
        tokenManager = TokenManager(context)

        // Create a logging interceptor to see request details in Logcat (for debugging)
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        }

        // Create an OkHttpClient and add both our interceptors
        val httpClient = OkHttpClient.Builder()
            .addInterceptor(AuthInterceptor(tokenManager))
            .addInterceptor(logging) // Add logging interceptor for easier debugging
            .build()

        val retrofit = Retrofit.Builder()
            .baseUrl(BuildConfig.API_BASE_URL)
            .client(httpClient) // Use our custom client
            .addConverterFactory(GsonConverterFactory.create())
            .build()

        apiService = retrofit.create(ApiService::class.java)
    }

    val instance: ApiService
        get() = apiService
}