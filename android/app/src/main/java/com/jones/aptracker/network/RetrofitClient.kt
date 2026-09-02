package com.jones.aptracker.network

import android.content.Context
import com.google.gson.GsonBuilder
import com.jones.aptracker.BuildConfig
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

object RetrofitClient {

    private lateinit var apiService: ApiService

    fun init(context: Context) {

        SessionManager.init(context)

        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        }

        val httpClient = OkHttpClient.Builder()
            // AuthInterceptor is the single place that decides a 401 ends the session.
            // There used to be an Authenticator here doing the same thing, but it ran
            // below the interceptor in OkHttp's chain and fired unconditionally, so it
            // always won the race and made the interceptor's rule unreachable. It never
            // returned a retry request -- the side effect was all it did. See #311.
            .addInterceptor(AuthInterceptor(TokenManager(context)))
            .addInterceptor(logging)
            .readTimeout(60, TimeUnit.SECONDS)
            .connectTimeout(15, TimeUnit.SECONDS)
            .build()

        // Create a custom Gson instance that processes nulls
        val gson = GsonBuilder()
            .setLenient()       // Handles malformed JSON gracefully
            .serializeNulls()   // CRITICAL: Sends {"key": null} instead of ignoring it
            .create()

        val retrofit = Retrofit.Builder()
            .baseUrl(BuildConfig.API_BASE_URL)
            .client(httpClient)
            .addConverterFactory(GsonConverterFactory.create(gson))
            .build()

        apiService = retrofit.create(ApiService::class.java)
    }

    val instance: ApiService
        get() = apiService
}