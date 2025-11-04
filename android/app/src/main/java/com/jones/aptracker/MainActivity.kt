package com.jones.aptracker

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.jones.aptracker.network.AuthRequest
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.SessionManager
import com.jones.aptracker.network.TokenManager
import com.jones.aptracker.ui.AppNavigation
import com.jones.aptracker.ui.AuthViewModel
import com.jones.aptracker.ui.theme.APTrackerTheme
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.launch
import net.openid.appauth.AuthorizationException
import net.openid.appauth.AuthorizationRequest
import net.openid.appauth.AuthorizationResponse
import net.openid.appauth.AuthorizationService
import net.openid.appauth.AuthorizationServiceConfiguration
import net.openid.appauth.ResponseTypeValues
import androidx.compose.ui.platform.LocalContext

class MainActivity : ComponentActivity() {

    private lateinit var authService: AuthorizationService
    private lateinit var tokenManager: TokenManager
    private val authViewModel: AuthViewModel by viewModels()
    private var currentCodeVerifier: String? = null
    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted: Boolean ->
        if (isGranted) {
            Toast.makeText(this, "Notifications enabled!", Toast.LENGTH_SHORT).show()
        } else {
            Toast.makeText(this, "Notifications are disabled. You can enable them in app settings.", Toast.LENGTH_LONG).show()
        }
    }


    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        authService = AuthorizationService(this)
        tokenManager = TokenManager(applicationContext)

        authViewModel.checkAuthStatus(tokenManager)

        val authLauncher = registerForActivityResult(
            ActivityResultContracts.StartActivityForResult()
        ) { result ->
            val data = result.data
            if (result.resultCode == RESULT_OK && data != null) {
                val response = AuthorizationResponse.fromIntent(data)
                val ex = AuthorizationException.fromIntent(data)
                val savedCodeVerifier = currentCodeVerifier

                if (response?.authorizationCode != null && savedCodeVerifier != null) {
                    exchangeCodeForToken(
                        code = response.authorizationCode!!,
                        codeVerifier = savedCodeVerifier
                    )
                } else {
                    val errorDetails = ex?.errorDescription ?: "Authorization cancelled or unknown error"
                    Log.e("LOGIN_FAILED", "Auth failed: $errorDetails")
                    Toast.makeText(this, "Login Failed: $errorDetails", Toast.LENGTH_LONG).show()
                    authViewModel.setLoading(false) // Make sure to stop loading
                }
            }
        }

        observeLogoutEvents()

        setContent {
            APTrackerTheme {
                val isLoggedIn by authViewModel.isLoggedIn.collectAsState()
                val isLoading by authViewModel.isLoading.collectAsState()
                val context = LocalContext.current
                val onLogout = { authViewModel.onLogout(context) }


                LaunchedEffect(isLoggedIn) {
                    if (isLoggedIn) {
                        authViewModel.registerDeviceToken(context)
                        checkAndRequestNotificationPermission()
                    }
                }

                AppNavigation(
                    isLoggedIn = isLoggedIn,
                    isLoading = isLoading,
                    onLoginClick = { startAuthentication(authLauncher) },
                    onLogoutClick = onLogout
                )
            }
        }
    }

    private fun observeLogoutEvents() {
        SessionManager.logoutEvent
            .onEach {
                Toast.makeText(
                    this,
                    "Your session has expired. Please log in again.",
                    Toast.LENGTH_LONG
                ).show()

                val intent = Intent(this, MainActivity::class.java).apply {
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
                }
                startActivity(intent)
            }
            .launchIn(lifecycleScope)
    }

    private fun checkAndRequestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val hasPermission = ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED

            if (!hasPermission) {
                requestPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    private fun startAuthentication(launcher: ActivityResultLauncher<Intent>) {
        val serviceConfig = AuthorizationServiceConfiguration(
            Uri.parse("https://discord.com/api/oauth2/authorize"),
            Uri.parse("https://discord.com/api/oauth2/token")
        )

        val clientId = BuildConfig.DISCORD_CLIENT_ID

        val redirectUri = Uri.parse("com.jones.aptracker:/oauth2redirect")

        val request = AuthorizationRequest.Builder(
            serviceConfig, clientId, ResponseTypeValues.CODE, redirectUri
        ).setScope("identify").build()

        currentCodeVerifier = request.codeVerifier

        launcher.launch(authService.getAuthorizationRequestIntent(request))
    }

    private fun exchangeCodeForToken(code: String, codeVerifier: String) {
        authViewModel.setLoading(true)
        lifecycleScope.launch {
            try {
                val redirectUri = "com.jones.aptracker:/oauth2redirect"
                val authRequest = AuthRequest(code, redirectUri, codeVerifier)

                val response = RetrofitClient.instance.exchangeCodeForToken(authRequest)
                tokenManager.saveToken(response.token)
                authViewModel.onLoginSuccess()
                Toast.makeText(this@MainActivity, "Login Successful!", Toast.LENGTH_SHORT).show()

                val intent = Intent(this@MainActivity, MainActivity::class.java).apply {
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
                }
                startActivity(intent)

            } catch (e: Exception) {
                val errorDetails = e.toString()
                Log.e("LOGIN_ERROR", "Failed to exchange token", e)
                Toast.makeText(this@MainActivity, "Exchange Failed: $errorDetails", Toast.LENGTH_LONG).show()
            } finally {
                authViewModel.setLoading(false)
            }
        }
    }


    override fun onDestroy() {
        super.onDestroy()
        authService.dispose()
    }
}