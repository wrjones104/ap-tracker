package com.jones.aptracker.ui

import android.net.Uri
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.jones.aptracker.R

@Composable
fun AppNavigation(
    isLoggedIn: Boolean,
    isLoading: Boolean,
    onLoginClick: () -> Unit,
    onLogoutClick: () -> Unit
) {
    if (isLoggedIn) {
        val navController = rememberNavController()
        MainNavHost(navController = navController, onLogoutClick = onLogoutClick)
    } else {
        LoginScreen(isLoading = isLoading, onLoginClick = onLoginClick)
    }
}

@Composable
fun MainNavHost(navController: NavHostController, onLogoutClick: () -> Unit) {
    NavHost(navController = navController, startDestination = "rooms") {
        composable("rooms") {
            RoomsScreen(
                onRoomClick = { roomId, roomAlias ->
                    navController.navigate("players/$roomId/${Uri.encode(roomAlias)}")
                },
                onHistoryClick = {
                    navController.navigate("history/global/All Rooms")
                },
                onLogoutClick = onLogoutClick,
                onSettingsClick = { navController.navigate("profile") }
            )
        }
        composable("profile") {
            ProfileScreen(
                onBackClick = { navController.popBackStack() },
                onLogout = onLogoutClick
            )
        }
        composable(
            route = "players/{roomId}/{roomAlias}",
            arguments = listOf(
                navArgument("roomId") { type = NavType.IntType },
                navArgument("roomAlias") { type = NavType.StringType }
            )
        ) { backStackEntry ->
            val roomId = backStackEntry.arguments?.getInt("roomId")!!
            val roomAlias = Uri.decode(backStackEntry.arguments?.getString("roomAlias")!!)
            PlayersScreen(
                roomId = roomId,
                roomAlias = roomAlias,
                onSave = { navController.popBackStack() }, // Navigate back after saving
                onHistoryClick = { navController.navigate("history/$roomId/${Uri.encode(roomAlias)}") } // Encode alias
            )
        }

        composable("history/global/All Rooms") {
            HistoryScreen(
                roomId = null, // Explicitly null for global
                roomAlias = "Global History", // Set a title
                onBackClick = { navController.popBackStack() } // Add back navigation
            )
        }

        composable(
            route = "history/{roomId}/{roomAlias}",
            arguments = listOf(
                navArgument("roomId") { type = NavType.IntType },
                navArgument("roomAlias") { type = NavType.StringType }
            )
        ) { backStackEntry ->
            val roomId = backStackEntry.arguments?.getInt("roomId")!!
            val roomAlias = Uri.decode(backStackEntry.arguments?.getString("roomAlias")!!)
            HistoryScreen(
                roomId = roomId,
                roomAlias = roomAlias,
                onBackClick = { navController.popBackStack() }
            )
        }
    }
}


@Composable
fun LoginScreen(isLoading: Boolean, onLoginClick: () -> Unit) {
    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Image(
                painter = painterResource(id = R.drawable.archipelago_tracker_banner),
                contentDescription = "App Banner",
                modifier = Modifier.fillMaxWidth(0.8f)
            )
            Spacer(modifier = Modifier.height(32.dp))
            Text("Welcome to AP Tracker", style = MaterialTheme.typography.headlineSmall)
            Spacer(modifier = Modifier.height(16.dp))
            if (isLoading) {
                CircularProgressIndicator()
            } else {
                Button(onClick = onLoginClick) {
                    Text("Login with Discord")
                }
            }
        }
    }
}