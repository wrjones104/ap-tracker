package com.jones.aptracker.ui.login

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.widget.Button
import androidx.appcompat.app.AppCompatActivity
import com.jones.aptracker.R
import net.openid.appauth.*

class LoginActivity : AppCompatActivity() {

    private lateinit var authService: AuthorizationService

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_login)

        authService = AuthorizationService(this)

        val loginButton: Button = findViewById(R.id.login_button)
        loginButton.setOnClickListener {
            startAuthentication()
        }
    }

    private fun startAuthentication() {
        val serviceConfig = AuthorizationServiceConfiguration(
            Uri.parse("https://discord.com/api/oauth2/authorize"), // Authorization endpoint
            Uri.parse("https://discord.com/api/oauth2/token")      // Token endpoint
        )

        // Use your actual Client ID from the .env file on your server
        val clientId = "YOUR_DISCORD_CLIENT_ID"
        // Use your corrected redirect URI
        val redirectUri = Uri.parse("com.jones.aptracker:/oauth2redirect")

        val request = AuthorizationRequest.Builder(
            serviceConfig,
            clientId,
            ResponseTypeValues.CODE,
            redirectUri
        ).setScope("identify").build()

        val authIntent = authService.getAuthorizationRequestIntent(request)

        // For now, we are using the older onActivityResult pattern.
        // We can upgrade this to the ActivityResultLauncher later.
        startActivityForResult(authIntent, RC_AUTH)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)

        if (requestCode == RC_AUTH) {
            val response = AuthorizationResponse.fromIntent(data!!)
            val ex = AuthorizationException.fromIntent(data)

            if (response != null) {
                // SUCCESS! We have the authorization code.
                val authCode = response.authorizationCode
                Log.d("LOGIN_SUCCESS", "Got auth code: $authCode")

                // TODO: We will now send this code to our backend.

            } else {
                // Handle failure or user cancellation
                Log.e("LOGIN_FAILED", "Authentication failed: ${ex?.errorDescription}")
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        authService.dispose()
    }

    companion object {
        private const val RC_AUTH = 100
    }
}