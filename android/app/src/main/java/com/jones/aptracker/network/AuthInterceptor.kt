package com.jones.aptracker.network

import okhttp3.Interceptor
import okhttp3.Response

class AuthInterceptor(private val tokenManager: TokenManager) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val originalRequest = chain.request()
        val token = tokenManager.getToken()

        // Blank counts as no credential. An empty token still produced the header
        // "Bearer " with nothing after it, which the server reads as a missing token.
        val hasCredential = !token.isNullOrBlank()

        val requestBuilder = originalRequest.newBuilder()
        if (hasCredential) {
            requestBuilder.addHeader("Authorization", "Bearer $token")
        }

        val request = requestBuilder.build()
        val response = chain.proceed(request)

        // A 401 means "your session ended" only if we actually presented a session.
        // When no credential went out, the request was never authenticated to begin
        // with, and treating that as an expiry runs the full logout -- which clears the
        // local database. That was reachable during the guest upgrade window. See #311.
        if (response.code == 401 && hasCredential) {
            SessionManager.logout(SessionManager.LogoutReason.SESSION_EXPIRED)
        }

        return response
    }
}
