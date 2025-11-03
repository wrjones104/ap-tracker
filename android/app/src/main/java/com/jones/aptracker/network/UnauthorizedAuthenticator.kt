package com.jones.aptracker.network

import okhttp3.Authenticator
import okhttp3.Request
import okhttp3.Response
import okhttp3.Route

class UnauthorizedAuthenticator : Authenticator {

    override fun authenticate(route: Route?, response: Response): Request? {
        // If we get a 401, our token is bad.
        // Trigger the local-only "self-destruct" sequence.
        if (response.code == 401) {
            SessionManager.logout()
        }

        // We can't fix the request, so return null.
        return null
    }
}