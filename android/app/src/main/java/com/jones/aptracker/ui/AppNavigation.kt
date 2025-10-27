package com.jones.aptracker.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
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

// This function determines whether to show the Login screen or the main app content.
@Composable
fun AppNavigation(
    isLoggedIn: Boolean,
    isLoading: Boolean,
    onLoginClick: () -> Unit,
    onLogoutClick: () -> Unit // <-- Pass logout callback
) {
    if (isLoggedIn) {
        val navController = rememberNavController()
        MainNavHost(navController = navController, onLogoutClick = onLogoutClick)
    } else {
        LoginScreen(isLoading = isLoading, onLoginClick = onLoginClick)
    }
}

// This is your main navigation graph for when the user is logged in.
@Composable
fun MainNavHost(navController: NavHostController, onLogoutClick: () -> Unit) {
    NavHost(navController = navController, startDestination = "rooms") {
        composable("rooms") {
            RoomsScreen(
                onRoomClick = { roomId, roomAlias ->
                    navController.navigate("players/$roomId/$roomAlias")
                },
                onHistoryClick = {
                    navController.navigate("history")
                },
                onLogoutClick = onLogoutClick
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
            val roomAlias = backStackEntry.arguments?.getString("roomAlias")!!
            PlayersScreen(
                roomId = roomId,
                roomAlias = roomAlias,
                onSave = { navController.popBackStack() },
                onHistoryClick = { navController.navigate("history/$roomId/$roomAlias") }
            )
        }
        composable("history") {
            HistoryScreen(roomId = null, roomAlias = null)
        }
        composable(
            route = "history/{roomId}/{roomAlias}",
            arguments = listOf(
                navArgument("roomId") { type = NavType.IntType },
                navArgument("roomAlias") { type = NavType.StringType }
            )
        ) { backStackEntry ->
            val roomId = backStackEntry.arguments?.getInt("roomId")!!
            val roomAlias = backStackEntry.arguments?.getString("roomAlias")!!
            HistoryScreen(roomId = roomId, roomAlias = roomAlias)
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