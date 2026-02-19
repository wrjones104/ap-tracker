package com.jones.aptracker.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.NotificationsPaused
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import java.time.Instant
import kotlinx.coroutines.delay

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
    onNavigateToArchived: () -> Unit,
    userViewModel: UserViewModel = viewModel(),
    roomsViewModel: RoomsViewModel = viewModel()
) {
    val bottomNavController = rememberNavController()

    // OBSERVE PROFILE FOR SNOOZE STATE
    val userProfile by userViewModel.userProfile.collectAsState()
    val trackedSlotsByRoom by userViewModel.trackedSlotsByRoom.collectAsState()
    var showUnSnoozeDialog by remember { mutableStateOf(false) }
    var now by remember { mutableStateOf(Instant.now()) }
    val rooms by roomsViewModel.rooms.collectAsState()
    var newRoomAliasToFind by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(rooms, newRoomAliasToFind) {
        if (newRoomAliasToFind != null) {
            val addedRoom = rooms.find { it.alias == newRoomAliasToFind }
            if (addedRoom != null) {
                onNavigateToPlayers(addedRoom.id, addedRoom.alias)
                newRoomAliasToFind = null // Reset state after navigation
            }
        }
    }

    // Hoisted State for Add Room Dialog
    var showAddRoomDialog by remember { mutableStateOf(false) }

    // Check if snooze is active
    val isGlobalSnoozeActive = remember(userProfile, now) {
        val snoozeTime = userProfile?.global_snooze_until
        if (snoozeTime == null) false else {
            try {
                Instant.parse(snoozeTime).isAfter(now)
            } catch (e: Exception) { false }
        }
    }

    // Check Slots
    val activeSlotSnoozes = remember(trackedSlotsByRoom) {
        trackedSlotsByRoom.flatMap { it.tracked_slots }.filter { slot ->
            val snoozeTime = slot.snooze_until
            if (snoozeTime == null) false else {
                try {
                    Instant.parse(snoozeTime).isAfter(Instant.now())
                } catch (e: Exception) { false }
            }
        }
    }

    val activeSnoozeDetails = remember(trackedSlotsByRoom, now) {
        val details = mutableListOf<String>()

        trackedSlotsByRoom.forEach { room ->
            room.tracked_slots.forEach { slot ->
                if (slot.snooze_until != null) {
                    try {
                        if (Instant.parse(slot.snooze_until).isAfter(now)) {
                            // Check for alias
                            val displayName = if (!slot.player_alias.isNullOrBlank()) {
                                "${slot.player_alias} (${slot.player_name})"
                            } else {
                                slot.player_name
                            }

                            // Format: "RoomAlias: Alias (OriginalName)"
                            details.add("${room.room_alias}: $displayName")
                        }
                    } catch (e: Exception) { /* ignore parse errors */ }
                }
            }
        }
        details
    }

    val isAnySnoozeActive = isGlobalSnoozeActive || activeSnoozeDetails.isNotEmpty()

    if (showUnSnoozeDialog) {
        val dialogTitle = if (isGlobalSnoozeActive) "Global Snooze Active" else "Active Snoozes"

        SnoozeDialog(
            title = dialogTitle,
            currentSnoozeUntil = userProfile?.global_snooze_until,
            activeSnoozeDetails = activeSnoozeDetails, // <--- PASS THE LIST HERE
            onDismiss = { showUnSnoozeDialog = false },
            onSnoozeSelected = { minutes ->
                if (minutes == 0) {
                    userViewModel.wakeUpEverything()
                } else {
                    userViewModel.setGlobalSnooze(minutes)
                }
                showUnSnoozeDialog = false
            }
        )
    }

    if (showAddRoomDialog) {
        AddRoomDialog(
            onDismiss = { showAddRoomDialog = false },
            onAdd = { url, alias, icon ->
                roomsViewModel.addRoom(url, alias, icon) {
                    // Trigger the effect above once the room is successfully added
                    newRoomAliasToFind = alias
                }
                showAddRoomDialog = false
            }
        )
    }

    val items = listOf(
        BottomNavItem.Rooms,
        BottomNavItem.Activity,
        BottomNavItem.Profile
    )

    // Track current route to decide which buttons to show
    val navBackStackEntry by bottomNavController.currentBackStackEntryAsState()
    val currentRoute = navBackStackEntry?.destination?.route

    Scaffold(
        bottomBar = {
            NavigationBar {
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
        },
        floatingActionButton = {
            // STACKED FABs (Column)
            Column(horizontalAlignment = Alignment.End) {

                // 1. "Snoozed" Indicator (Top)
                if (isAnySnoozeActive) {
                    ExtendedFloatingActionButton(
                        text = {
                            // Optional: Show count
                            if (activeSlotSnoozes.isNotEmpty() && !isGlobalSnoozeActive) {
                                Text("Snoozed (${activeSlotSnoozes.size})")
                            } else {
                                Text("Snoozed")
                            }
                        },
                        icon = { Icon(Icons.Default.NotificationsPaused, contentDescription = "Un-snooze") },
                        onClick = { showUnSnoozeDialog = true },
                        containerColor = MaterialTheme.colorScheme.secondaryContainer,
                        contentColor = MaterialTheme.colorScheme.onSecondaryContainer
                    )
                }

                // 2. "Add Room" Button (Bottom - Only on Rooms Tab)
                if (currentRoute == BottomNavItem.Rooms.route) {
                    FloatingActionButton(onClick = { showAddRoomDialog = true }) {
                        Icon(Icons.Default.Add, contentDescription = "Add Room")
                    }
                }
            }
        }
    ) { innerPadding ->
        NavHost(
            navController = bottomNavController,
            startDestination = BottomNavItem.Rooms.route,
            modifier = Modifier.padding(bottom = innerPadding.calculateBottomPadding())
        ) {
            composable(BottomNavItem.Rooms.route) {
                RoomsScreen(
                    roomsViewModel = roomsViewModel,
                    userViewModel = userViewModel,
                    onRoomClick = onNavigateToRoomHistory,
                    onManageSlotsClick = onNavigateToPlayers,
                )
            }
            composable(BottomNavItem.Activity.route) {
                ActivityFeedScreen(
                    userViewModel = userViewModel
                )
            }
            composable(BottomNavItem.Profile.route) {
                ProfileScreen(
                    userViewModel = userViewModel, // Ensures Profile uses the same VM
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