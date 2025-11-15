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
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jones.aptracker.network.AuthRequest
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.SessionManager
import com.jones.aptracker.network.TokenManager
import com.jones.aptracker.ui.AppNavigation
import com.jones.aptracker.ui.AppVersionState
import com.jones.aptracker.ui.AuthViewModel
import com.jones.aptracker.ui.MainViewModel
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
import com.google.gson.Gson
import com.jones.aptracker.network.AuthErrorResponse
import retrofit2.HttpException
import androidx.compose.material3.TextButton

class MainActivity : ComponentActivity() {

    private lateinit var authService: AuthorizationService
    lateinit var tokenManager: TokenManager // Made public for composables
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
        tokenManager = TokenManager(applicationContext) // Initialize class property

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
                    authViewModel.setLoading(false)
                }
            }
        }

        observeLogoutEvents()

        setContent {
            APTrackerTheme {
                val onGuestUpgradeClick = {
                    authViewModel.startGuestUpgrade(
                        context = this@MainActivity,
                        onAuth = { startAuthentication(authLauncher) }
                    )
                }
                VersionGate(
                    authViewModel = authViewModel,
                    onStartDiscordAuth = { startAuthentication(authLauncher) },
                    onStartGuestAuth = { startGuestAuthentication() },
                    onCheckNotificationPermission = { checkAndRequestNotificationPermission() },
                    onGuestUpgradeClick = onGuestUpgradeClick
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

    // Made public (removed private) so composable can call it
    fun exchangeCodeForToken(code: String, codeVerifier: String) {
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
                var errorDetails = e.toString()

                if (e is HttpException) {
                    if (e.code() == 409) {
                        try {
                            val errorJson = e.response()?.errorBody()?.string()
                            val errorResponse = Gson().fromJson(errorJson, AuthErrorResponse::class.java)
                            if (errorResponse.error == "account_conflict") {
                                authViewModel.onMergeConflict(code, codeVerifier)
                            } else {
                                errorDetails = "An unknown conflict occurred."
                                Toast.makeText(this@MainActivity, errorDetails, Toast.LENGTH_LONG).show()
                            }
                        } catch (parseError: Exception) {
                            errorDetails = "This Discord account is already in use by another user."
                            Toast.makeText(this@MainActivity, errorDetails, Toast.LENGTH_LONG).show()
                        }
                    } else {
                        errorDetails = "Exchange Failed: ${e.code()} ${e.message()}"
                        Toast.makeText(this@MainActivity, errorDetails, Toast.LENGTH_LONG).show()
                    }
                } else {
                    Log.e("LOGIN_ERROR", "Failed to exchange token", e)
                    Toast.makeText(this@MainActivity, errorDetails, Toast.LENGTH_LONG).show()
                }
            } finally {
                authViewModel.setLoading(false)
            }
        }
    }

    private fun startGuestAuthentication() {
        authViewModel.setLoading(true)
        lifecycleScope.launch {
            try {
                val response = RetrofitClient.instance.loginAsGuest()

                tokenManager.saveToken(response.token)

                authViewModel.onLoginSuccess()
                Toast.makeText(this@MainActivity, "Logged in as Guest!", Toast.LENGTH_SHORT).show()

                val intent = Intent(this@MainActivity, MainActivity::class.java).apply {
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
                }
                startActivity(intent)

            } catch (e: Exception) {
                val errorDetails = e.toString()
                Log.e("GUEST_LOGIN_ERROR", "Failed to login as guest", e)
                Toast.makeText(this@MainActivity, "Guest Login Failed: $errorDetails", Toast.LENGTH_LONG).show()
                authViewModel.setLoading(false)
            }
        }
    }


    override fun onDestroy() {
        super.onDestroy()
        authService.dispose()
    }
}

@Composable
fun VersionGate(
    authViewModel: AuthViewModel,
    mainViewModel: MainViewModel = viewModel(),
    onStartDiscordAuth: () -> Unit,
    onStartGuestAuth: () -> Unit,
    onCheckNotificationPermission: () -> Unit,
    onGuestUpgradeClick: () -> Unit
) {
    val versionState by mainViewModel.versionState.collectAsState()
    val showMergeConflict by authViewModel.showMergeConflictDialog.collectAsState()
    val activity = (LocalContext.current as? MainActivity)

    when (val state = versionState) {
        is AppVersionState.Checking -> {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        }
        is AppVersionState.UpToDate -> {
            val isLoggedIn by authViewModel.isLoggedIn.collectAsState()
            val isLoading by authViewModel.isLoading.collectAsState()
            val context = LocalContext.current
            val onLogout = { authViewModel.onLogout(context) }

            LaunchedEffect(isLoggedIn) {
                if (isLoggedIn) {
                    authViewModel.registerDeviceToken(context)
                    onCheckNotificationPermission()
                }
            }


            AppNavigation(
                isLoggedIn = isLoggedIn,
                isLoading = isLoading,
                onDiscordLoginClick = onStartDiscordAuth,
                onGuestLoginClick = onStartGuestAuth,
                onLogoutClick = onLogout,
                onGuestUpgradeClick = onGuestUpgradeClick
            )
        }
        is AppVersionState.Outdated -> {
            UpdateRequiredScreen(storeUrl = state.storeUrl)
        }
        is AppVersionState.Error -> {
            ErrorScreen(message = state.message, onRetry = { mainViewModel.checkAppVersion() })
        }
    }
}


@Composable
fun UpdateRequiredScreen(storeUrl: String) {
    val context = LocalContext.current
    val githubReleasesUrl = "https://github.com/wrjones104/ap-tracker/releases"

    AlertDialog(
        onDismissRequest = { /* Do nothing, cannot be dismissed */ },
        title = { Text("Update Required") },
        text = { Text("This version of AP Tracker is no longer supported. Please update to the latest version to continue.") },
        confirmButton = {
            Button(onClick = {
                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(githubReleasesUrl))
                context.startActivity(intent)
            }) {
                Text("Go to Releases")
            }
        },
        dismissButton = null
    )
}

@Composable
fun ErrorScreen(message: String, onRetry: () -> Unit) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = "An error occurred:",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface
            )
            Text(
                text = message,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(16.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Button(onClick = onRetry) {
                Text("Retry")
            }
        }
    }
}