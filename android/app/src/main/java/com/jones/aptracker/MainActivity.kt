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
import androidx.activity.enableEdgeToEdge
import androidx.activity.compose.setContent
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.jones.aptracker.network.AuthErrorResponse
import com.jones.aptracker.network.AuthRequest
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.SessionManager
import com.jones.aptracker.network.TokenManager
import com.jones.aptracker.ui.AppNavigation
import com.jones.aptracker.ui.AppVersionState
import com.jones.aptracker.ui.AuthViewModel
import com.jones.aptracker.ui.MainViewModel
import com.jones.aptracker.ui.theme.APTrackerTheme
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.launch
import net.openid.appauth.AuthorizationException
import net.openid.appauth.AuthorizationRequest
import net.openid.appauth.AuthorizationResponse
import net.openid.appauth.AuthorizationService
import net.openid.appauth.AuthorizationServiceConfiguration
import net.openid.appauth.ResponseTypeValues
import retrofit2.HttpException

class MainActivity : ComponentActivity() {

    private lateinit var authService: AuthorizationService
    lateinit var tokenManager: TokenManager
    private val authViewModel: AuthViewModel by viewModels()
    private var isLoggingOut = false

    // State for the summary sheet
    private val bundledItemsState = mutableStateOf<List<String>?>(null)
    private val bundleTypeState = mutableStateOf<String?>(null)
    private val targetTabState = mutableStateOf<String?>(null)

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
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)

        authService = AuthorizationService(this)
        tokenManager = TokenManager(applicationContext)

        authViewModel.checkAuthStatus(tokenManager)

        // Handle cold start from notification
        handleIntent(intent)

        val authLauncher = registerForActivityResult(
            ActivityResultContracts.StartActivityForResult()
        ) { result ->
            // Handle the user manually closing the browser or backing out
            if (result.resultCode == RESULT_CANCELED) {
                Log.d("LOGIN_CANCELED", "User backed out of the login flow.")
                authViewModel.setLoading(false)
                return@registerForActivityResult
            }

            val data = result.data
            if (result.resultCode == RESULT_OK && data != null) {
                val response = AuthorizationResponse.fromIntent(data)
                val ex = AuthorizationException.fromIntent(data)

                // Retrieve the code verifier from SharedPreferences
                val prefs = getSharedPreferences("auth_prefs", MODE_PRIVATE)
                val savedCodeVerifier = prefs.getString("code_verifier", null)

                // Clean it up immediately so it doesn't linger
                prefs.edit().remove("code_verifier").apply()

                if (response?.authorizationCode != null && savedCodeVerifier != null) {
                    // Success! Exchange the code.
                    exchangeCodeForToken(
                        code = response.authorizationCode!!,
                        codeVerifier = savedCodeVerifier
                    )
                } else {
                    // Something went wrong (e.g. Discord rejected it, or we somehow lost the verifier again)
                    val errorDetails = ex?.errorDescription ?: "Authorization cancelled or verifier lost"
                    Log.e("LOGIN_FAILED", "Auth failed: $errorDetails")
                    Toast.makeText(this, "Login Failed: $errorDetails", Toast.LENGTH_LONG).show()
                    authViewModel.setLoading(false)
                }
            } else {
                // Fallback for any other weird result codes
                authViewModel.setLoading(false)
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

                val summaryItems = bundledItemsState.value
                val bundleType = bundleTypeState.value

                VersionGate(
                    authViewModel = authViewModel,
                    onStartDiscordAuth = { startAuthentication(authLauncher) },
                    onStartGuestAuth = { startGuestAuthentication() },
                    onCheckNotificationPermission = { checkAndRequestNotificationPermission() },
                    onGuestUpgradeClick = onGuestUpgradeClick,
                    targetTab = targetTabState.value,
                    onTargetTabConsumed = {
                        targetTabState.value = null
                        intent?.removeExtra("target_tab")
                    }
                )

                if (summaryItems != null) {
                    BundleSummarySheet(
                        items = summaryItems,
                        type = bundleType,
                        onDismiss = {
                            bundledItemsState.value = null
                            bundleTypeState.value = null
                            intent?.removeExtra("bundled_items")
                            intent?.removeExtra("bundle_type")
                        }
                    )
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)

        lifecycleScope.launch {
            delay(150)
            handleIntent(intent)
        }
    }

    private fun handleIntent(intent: Intent?) {
        val targetTab = intent?.getStringExtra("target_tab")
        if (targetTab != null) {
            targetTabState.value = targetTab
        }

        val jsonStr = intent?.getStringExtra("bundled_items")
        val bundleType = intent?.getStringExtra("bundle_type")
        if (jsonStr == null) {
            Log.d("BUNDLE_DEBUG", "No bundled_items extra found in intent.")
            return
        }

        Log.d("BUNDLE_DEBUG", "Found bundled_items JSON: $jsonStr, Type: $bundleType")

        try {
            val type = object : TypeToken<List<String>>() {}.type
            val items: List<String> = Gson().fromJson(jsonStr, type)

            if (items.isNotEmpty()) {
                Log.d("BUNDLE_DEBUG", "Parsed ${items.size} items successfully.")
                bundledItemsState.value = items
                bundleTypeState.value = bundleType
            } else {
                Log.d("BUNDLE_DEBUG", "Parsed list was empty.")
            }
        } catch (e: Exception) {
            Log.e("BUNDLE_DEBUG", "Failed to parse bundled_items JSON", e)
        }
    }

    private fun observeLogoutEvents() {
        SessionManager.logoutEvent
            .onEach { reason ->
                if (isLoggingOut) return@onEach
                isLoggingOut = true

                if (reason == SessionManager.LogoutReason.SESSION_EXPIRED) {
                    Toast.makeText(this, "Session expired. Please log in again.", Toast.LENGTH_LONG).show()
                }

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

        // Save the verifier to SharedPreferences to survive Activity process death
        val codeVerifier = request.codeVerifier
        getSharedPreferences("auth_prefs", MODE_PRIVATE)
            .edit()
            .putString("code_verifier", codeVerifier)
            .apply()

        launcher.launch(authService.getAuthorizationRequestIntent(request))
    }

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
                Log.e("GUEST_LOGIN_ERROR", "Failed to login as guest", e)
                Toast.makeText(this@MainActivity, "Guest Login Failed.", Toast.LENGTH_LONG).show()
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

@Composable
fun VersionGate(
    authViewModel: AuthViewModel,
    mainViewModel: MainViewModel = viewModel(),
    onStartDiscordAuth: () -> Unit,
    onStartGuestAuth: () -> Unit,
    onCheckNotificationPermission: () -> Unit,
    onGuestUpgradeClick: () -> Unit,
    targetTab: String? = null,
    onTargetTabConsumed: () -> Unit = {}
) {
    val versionState by mainViewModel.versionState.collectAsState()

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
                onGuestUpgradeClick = onGuestUpgradeClick,
                targetTab = targetTab,
                onTargetTabConsumed = onTargetTabConsumed
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
    val playStoreUrl = "https://play.google.com/store/apps/details?id=com.jones.aptracker"
    AlertDialog(
        onDismissRequest = { },
        title = { Text("Update Required") },
        text = { Text("This version of AP Alerts is no longer supported. Please update.") },
        confirmButton = {
            Button(onClick = {
                val urlToOpen = if (storeUrl.isNotEmpty()) storeUrl else playStoreUrl
                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(urlToOpen))
                context.startActivity(intent)
            }) { Text("Update") }
        },
        dismissButton = null
    )
}

@Composable
fun ErrorScreen(message: String, onRetry: () -> Unit) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text("An error occurred:", style = MaterialTheme.typography.titleMedium)
            Text(message, modifier = Modifier.padding(16.dp))
            Button(onClick = onRetry) { Text("Retry") }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BundleSummarySheet(
    items: List<String>,
    type: String?,
    onDismiss: () -> Unit
) {
    val isHint = type == "hint"
    val titleText = if (isHint) "New Hints" else "New Items Received"
    val subtitleText = if (isHint) {
        "You just received a bundle of ${items.size} hints."
    } else {
        "You just received a bundle of ${items.size} items."
    }

    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp)
                .padding(bottom = 32.dp)
                .navigationBarsPadding()
        ) {
            Text(
                text = titleText,
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.padding(bottom = 8.dp)
            )
            Text(
                text = subtitleText,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(bottom = 16.dp)
            )

            HorizontalDivider()

            LazyColumn(
                modifier = Modifier.fillMaxWidth().weight(1f, fill = false)
            ) {
                items(items) { item ->
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = item,
                            style = MaterialTheme.typography.bodyLarge
                        )
                    }
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f))
                }
            }

            Spacer(modifier = Modifier.height(24.dp))
            Button(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) {
                Text("Awesome")
            }
        }
    }
}