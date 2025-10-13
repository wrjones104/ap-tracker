package com.jones.aptracker

import android.Manifest
import android.os.Build
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.google.firebase.ktx.Firebase
import com.google.firebase.messaging.ktx.messaging
import com.jones.aptracker.ui.PlayersScreen
import com.jones.aptracker.ui.RoomsScreen
import com.jones.aptracker.ui.theme.APTrackerTheme
import androidx.lifecycle.lifecycleScope
import com.jones.aptracker.network.RegisterDeviceRequest
import com.jones.aptracker.ui.HistoryScreen
import com.jones.aptracker.network.RetrofitClient
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    // ... (permission logic is the same)
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
                // --- NAVIGATION SETUP ---
                val navController = rememberNavController()

                NavHost(navController = navController, startDestination = "rooms") {
                    // Our main screen with the list of rooms
                    composable("rooms") {
                        RoomsScreen(
                            onRoomClick = { roomId, roomAlias ->
                                // When a room is clicked, navigate to the players screen
                                navController.navigate("players/$roomId/$roomAlias")
                            }
                        )
                    }

                    // Our new screen to select players
                    composable("players/{roomId}/{roomAlias}") { backStackEntry ->
                        val roomId = backStackEntry.arguments?.getString("roomId")?.toIntOrNull() ?: 0
                        val roomAlias = backStackEntry.arguments?.getString("roomAlias") ?: "Room"
                        PlayersScreen(
                            roomId = roomId,
                            roomAlias = roomAlias,
                            onSave = { navController.popBackStack() },
                            // **THE FIX**: Handle the click
                            onHistoryClick = {
                                navController.navigate("history/$roomId/$roomAlias")
                            }
                        )
                    }
                    composable("history/{roomId}/{roomAlias}") { backStackEntry ->
                        val roomId = backStackEntry.arguments?.getString("roomId")?.toIntOrNull() ?: 0
                        val roomAlias = backStackEntry.arguments?.getString("roomAlias") ?: "History"
                        HistoryScreen(roomId = roomId, roomAlias = roomAlias)
                    }
                }
            }
        }
    }

    // ... (getDeviceToken function is the same)
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
        // Use lifecycleScope to launch a background task from an Activity
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