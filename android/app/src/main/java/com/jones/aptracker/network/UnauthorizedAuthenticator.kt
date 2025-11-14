package com.jones.aptracker.network

import okhttp3.Authenticator
import okhttp3.Request
import okhttp3.Response
import okhttp3.Route

class UnauthorizedAuthenticator : Authenticator {

    override fun authenticate(route: Route?, response: Response): Request? {
        if (response.code == 401) {
            SessionManager.logout()
        }

        return null
    }
}