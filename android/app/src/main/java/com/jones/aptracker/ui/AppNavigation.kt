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
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
    onDiscordLoginClick: () -> Unit,
    onGuestLoginClick: () -> Unit,
    onLogoutClick: () -> Unit,
    onGuestUpgradeClick: () -> Unit
) {
    if (isLoggedIn) {
        val navController = rememberNavController()
        MainNavHost(
            navController = navController,
            onLogoutClick = onLogoutClick,
            onGuestUpgradeClick = onGuestUpgradeClick
        )
    } else {
        LoginScreen(
            isLoading = isLoading,
            onDiscordLoginClick = onDiscordLoginClick,
            onGuestLoginClick = onGuestLoginClick
        )
    }
}

@Composable
fun MainNavHost(
    navController: NavHostController,
    onLogoutClick: () -> Unit,
    onGuestUpgradeClick: () -> Unit
) {
    // Start destination is now 'home', which holds the Bottom Bar
    NavHost(navController = navController, startDestination = "home") {

        // --- THE MAIN CONTAINER (Bottom Nav) ---
        composable("home") {
            MainScreen(
                onLogoutClick = onLogoutClick,
                onGuestUpgradeClick = onGuestUpgradeClick,
                onNavigateToRoomHistory = { roomId, roomAlias ->
                    navController.navigate("history/$roomId/${Uri.encode(roomAlias)}")
                },
                onNavigateToGlobalHistory = {
                    navController.navigate("history/global/All Rooms")
                },
                onNavigateToPlayers = { roomId, roomAlias ->
                    navController.navigate("players/$roomId/${Uri.encode(roomAlias)}")
                },
                onNavigateToIgnoreList = {
                    navController.navigate("ignore_list")
                },
                onNavigateToCredits = {
                    navController.navigate("credits")
                },
                onNavigateToSettings = { navController.navigate("settings") },
                onNavigateToArchived = { navController.navigate("archived_rooms") }
            )
        }

        // --- DETAIL SCREENS (Cover the Bottom Bar) ---

        composable("ignore_list") {
            IgnoreListScreen(
                onBackClick = { navController.popBackStack() }
            )
        }

        composable("credits") {
            CreditsScreen(
                onBackClick = { navController.popBackStack() }
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
                onSave = { navController.popBackStack() },
            )
        }

        composable("history/global/All Rooms") {
            HistoryScreen(
                roomId = null,
                roomAlias = "Global History",
                onBackClick = { navController.popBackStack() }
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
        composable("settings") {
            SettingsScreen(
                onBackClick = { navController.popBackStack() },
                onNavigateToSlotOverrides = { navController.navigate("slot_overrides") }
            )
        }

        composable("slot_overrides") {
            SlotOverridesScreen(
                onBackClick = { navController.popBackStack() }
            )
        }

        composable("archived_rooms") {
            ArchivedRoomsScreen(
                onBackClick = { navController.popBackStack()}
            )
        }
    }
}

// LoginScreen remains unchanged...
@Composable
fun LoginScreen(
    isLoading: Boolean,
    onDiscordLoginClick: () -> Unit,
    onGuestLoginClick: () -> Unit
) {
    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            val bannerImages = listOf(
                R.drawable.login_1,
                R.drawable.login_2,
                R.drawable.login_3,
            )
            val randomBanner by remember { mutableStateOf(bannerImages.random()) }
            Image(
                painter = painterResource(id = randomBanner),
                contentDescription = "App Banner",
                modifier = Modifier.fillMaxWidth(0.8f)
            )
            Spacer(modifier = Modifier.height(32.dp))
            Spacer(modifier = Modifier.height(16.dp))
            if (isLoading) {
                CircularProgressIndicator()
            } else {
                Button(onClick = onDiscordLoginClick) {
                    Text("Login with Discord")
                }
                Spacer(modifier = Modifier.height(8.dp))
                TextButton(onClick = onGuestLoginClick) {
                    Text("Continue as Guest")
                }
            }
        }
    }
}