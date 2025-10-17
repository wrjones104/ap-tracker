package com.jones.aptracker

import android.Manifest
import android.os.Build
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.lifecycleScope
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.google.firebase.ktx.Firebase
import com.google.firebase.messaging.ktx.messaging
import com.jones.aptracker.network.RegisterDeviceRequest
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.ui.HistoryScreen
import com.jones.aptracker.ui.PlayersScreen
import com.jones.aptracker.ui.RoomsScreen
import com.jones.aptracker.ui.theme.APTrackerTheme
import kotlinx.coroutines.launch
import java.net.URLDecoder // <-- ADD THIS IMPORT
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

class MainActivity : ComponentActivity() {

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { isGranted: Boolean ->
        if (isGranted) { Log.d("PERMISSION", "Notification permission granted.")
        } else { Log.d("PERMISSION", "Notification permission denied.") }
    }
    private fun askNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            requestPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }


    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        askNotificationPermission()
        getDeviceToken()

        setContent {
            APTrackerTheme {
                val navController = rememberNavController()

                NavHost(navController = navController, startDestination = "rooms") {
                    composable("rooms") {
                        RoomsScreen(
                            onRoomClick = { roomId, roomAlias ->
                                val encodedAlias = URLEncoder.encode(roomAlias, StandardCharsets.UTF_8.toString())
                                navController.navigate("players/$roomId/$encodedAlias")
                            },
                            onHistoryClick = {
                                navController.navigate("history")
                            }
                        )
                    }

                    composable("players/{roomId}/{roomAlias}") { backStackEntry ->
                        val roomId = backStackEntry.arguments?.getString("roomId")?.toIntOrNull() ?: 0
                        // **THE FIX**: Decode the alias from the URL
                        val encodedAlias = backStackEntry.arguments?.getString("roomAlias") ?: "Room"
                        val roomAlias = URLDecoder.decode(encodedAlias, StandardCharsets.UTF_8.toString())

                        PlayersScreen(
                            roomId = roomId,
                            roomAlias = roomAlias,
                            onSave = { navController.popBackStack() },
                            onHistoryClick = {
                                val reEncodedAlias = URLEncoder.encode(roomAlias, StandardCharsets.UTF_8.toString())
                                navController.navigate("history?roomId=$roomId&roomAlias=$reEncodedAlias")
                            }
                        )
                    }
                    composable(
                        route = "history?roomId={roomId}&roomAlias={roomAlias}",
                        arguments = listOf(
                            navArgument("roomId") {
                                type = NavType.StringType
                                nullable = true
                            },
                            navArgument("roomAlias") {
                                type = NavType.StringType
                                nullable = true
                            }
                        )
                    ) { backStackEntry ->
                        val roomId = backStackEntry.arguments?.getString("roomId")?.toIntOrNull()
                        val encodedAlias = backStackEntry.arguments?.getString("roomAlias")
                        val roomAlias = encodedAlias?.let { URLDecoder.decode(it, StandardCharsets.UTF_8.toString()) }

                        HistoryScreen(roomId = roomId, roomAlias = roomAlias)
                    }
                }
            }
        }
    }

    private fun getDeviceToken() {
        Firebase.messaging.token.addOnCompleteListener { task ->
            if (!task.isSuccessful) {
                Log.w("FCM", "Fetching FCM registration token failed", task.exception)
                return@addOnCompleteListener
            }
            val token = task.result
            Log.d("FCM_TOKEN", token)
            sendTokenToServer(token)
        }
    }

    private fun sendTokenToServer(token: String) {
        lifecycleScope.launch {
            try {
                val request = RegisterDeviceRequest(token = token)
                RetrofitClient.instance.registerDevice(request)
                Log.d("API", "Device token sent to server successfully.")
            } catch (e: Exception) {
                Log.e("API", "Failed to send device token to server.", e)
            }
        }
    }
}