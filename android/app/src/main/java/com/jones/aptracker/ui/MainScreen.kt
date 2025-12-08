package com.jones.aptracker.ui

import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController

sealed class BottomNavItem(val route: String, val icon: ImageVector, val label: String) {
    object Rooms : BottomNavItem("rooms_tab", Icons.Default.Home, "Rooms")
    object Activity : BottomNavItem("activity_tab", Icons.Default.List, "Activity")
    object Profile : BottomNavItem("profile_tab", Icons.Default.Person, "Me")
}

@Composable
fun MainScreen(
    onLogoutClick: () -> Unit,
    onGuestUpgradeClick: () -> Unit,
    onNavigateToRoomHistory: (Int, String) -> Unit,
    onNavigateToGlobalHistory: () -> Unit,
    onNavigateToPlayers: (Int, String) -> Unit,
    onNavigateToIgnoreList: () -> Unit,
    onNavigateToCredits: () -> Unit,
    onNavigateToSettings: () -> Unit,
    onNavigateToArchived: () -> Unit
) {
    val bottomNavController = rememberNavController()

    val items = listOf(
        BottomNavItem.Rooms,
        BottomNavItem.Activity,
        BottomNavItem.Profile
    )

    Scaffold(
        bottomBar = {
            NavigationBar {
                var modifier = Modifier.height(68.dp)
                val navBackStackEntry by bottomNavController.currentBackStackEntryAsState()
                val currentRoute = navBackStackEntry?.destination?.route

                items.forEach { item ->
                    NavigationBarItem(
                        icon = { Icon(item.icon, contentDescription = item.label) },
                        label = { Text(item.label) },
                        selected = currentRoute == item.route,
                        onClick = {
                            bottomNavController.navigate(item.route) {
                                popUpTo(bottomNavController.graph.findStartDestination().id) {
                                    saveState = true
                                }
                                launchSingleTop = true
                                restoreState = true
                            }
                        }
                    )
                }
            }
        }
    ) { innerPadding ->
        NavHost(
            navController = bottomNavController,
            startDestination = BottomNavItem.Rooms.route,
            modifier = Modifier.padding(bottom = innerPadding.calculateBottomPadding())
        ) {
            // TAB 1: ROOMS
            composable(BottomNavItem.Rooms.route) {
                RoomsScreen(
                    onRoomClick = onNavigateToRoomHistory,
                    onManageSlotsClick = onNavigateToPlayers,
                )
            }

            // TAB 2: ACTIVITY
            composable(BottomNavItem.Activity.route) {
                ActivityFeedScreen()
            }

            // TAB 3: PROFILE
            composable(BottomNavItem.Profile.route) {
                ProfileScreen(
                    onLogoutClick = onLogoutClick,
                    onGuestUpgradeClick = onGuestUpgradeClick,
                    onIgnoreListClick = onNavigateToIgnoreList,
                    onCreditsClick = onNavigateToCredits,
                    onNavigateToSettings = onNavigateToSettings,
                    onNavigateToArchived = onNavigateToArchived
                )
            }
        }
    }
}