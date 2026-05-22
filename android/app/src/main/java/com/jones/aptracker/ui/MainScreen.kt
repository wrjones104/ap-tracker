package com.jones.aptracker.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.NotificationsPaused
import androidx.compose.material.icons.filled.ViewList
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalUriHandler //
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import coil.compose.AsyncImage
import java.time.Instant

sealed class BottomNavItem(val route: String, val icon: ImageVector, val label: String) {
    object Rooms : BottomNavItem("rooms_tab", Icons.Default.Home, "Rooms")
    object Slots : BottomNavItem("slots_tab", Icons.Default.ViewList, "Slots")
    object Activity : BottomNavItem("activity_tab", Icons.Default.List, "Activity")
    object Profile : BottomNavItem("profile_tab", Icons.Default.Person, "Me")
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(
    onLogoutClick: () -> Unit,
    onGuestUpgradeClick: () -> Unit,
    onNavigateToPlayers: (Int, String) -> Unit,
    onNavigateToIgnoreList: () -> Unit,
    onNavigateToCredits: () -> Unit,
    onNavigateToSettings: () -> Unit,
    onNavigateToArchived: () -> Unit,
    onNavigateToSlotDetail: (Int, Int) -> Unit,
    userViewModel: UserViewModel = viewModel(),
    roomsViewModel: RoomsViewModel = viewModel(),
    historyViewModel: HistoryViewModel = viewModel()
) {
    val bottomNavController = rememberNavController()

    val historyFilter by historyViewModel.historyFilter.collectAsState()
    val roomNames by historyViewModel.roomNames.collectAsState()

    LaunchedEffect(historyViewModel) {
        historyViewModel.navigateToActivityTab.collect {
            bottomNavController.navigate(BottomNavItem.Activity.route) {
                popUpTo(bottomNavController.graph.findStartDestination().id) { saveState = true }
                launchSingleTop = true
                restoreState = true
            }
        }
    }

    // --- 1. Get URI Handler for links ---
    val uriHandler = LocalUriHandler.current

    val userProfile by userViewModel.userProfile.collectAsState()
    val trackedSlotsByRoom by userViewModel.trackedSlotsByRoom.collectAsState()
    val isSyncingCheese by roomsViewModel.isSyncingCheese.collectAsState()
    val rooms by roomsViewModel.rooms.collectAsState()
    val isAddingRoom by roomsViewModel.isAddingRoom.collectAsState()

    var showUnSnoozeDialog by remember { mutableStateOf(false) }
    var now by remember { mutableStateOf(Instant.now()) }
    var newRoomAliasToFind by remember { mutableStateOf<String?>(null) }
    var showAddRoomDialog by remember { mutableStateOf(false) }

    // --- NAVIGATION EFFECT ---
    LaunchedEffect(rooms, newRoomAliasToFind) {
        if (newRoomAliasToFind != null) {
            val addedRoom = rooms.find { it.alias == newRoomAliasToFind }
            if (addedRoom != null) {
                onNavigateToPlayers(addedRoom.id, addedRoom.alias)
                newRoomAliasToFind = null
            }
        }
    }

    // --- SNOOZE LOGIC ---
    val isGlobalSnoozeActive = remember(userProfile, now) {
        val snoozeTime = userProfile?.global_snooze_until
        if (snoozeTime == null) false else {
            try { Instant.parse(snoozeTime).isAfter(now) } catch (e: Exception) { false }
        }
    }

    val activeSlotSnoozes = remember(trackedSlotsByRoom) {
        trackedSlotsByRoom.flatMap { it.tracked_slots }.filter { slot ->
            val snoozeTime = slot.snooze_until
            if (snoozeTime == null) false else {
                try { Instant.parse(snoozeTime).isAfter(Instant.now()) } catch (e: Exception) { false }
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
                            val displayName = if (!slot.player_alias.isNullOrBlank()) "${slot.player_alias} (${slot.player_name})" else slot.player_name
                            details.add("${room.room_alias}: $displayName")
                        }
                    } catch (e: Exception) { }
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
            activeSnoozeDetails = activeSnoozeDetails,
            onDismiss = { showUnSnoozeDialog = false },
            onSnoozeSelected = { minutes ->
                if (minutes == 0) userViewModel.wakeUpEverything() else userViewModel.setGlobalSnooze(minutes)
                showUnSnoozeDialog = false
            }
        )
    }

    if (showAddRoomDialog) {
        AddRoomDialog(
            isAdding = isAddingRoom,
            onDismiss = { showAddRoomDialog = false },
            onAdd = { url, alias, icon ->
                roomsViewModel.addRoom(url, alias, icon) {
                    newRoomAliasToFind = alias
                    showAddRoomDialog = false
                }
            }
        )
    }

    val items = listOf(BottomNavItem.Rooms, BottomNavItem.Slots, BottomNavItem.Activity, BottomNavItem.Profile)
    val navBackStackEntry by bottomNavController.currentBackStackEntryAsState()
    val currentRoute = navBackStackEntry?.destination?.route

    Scaffold(
        topBar = {
            val titleText = when (currentRoute) {
                BottomNavItem.Rooms.route -> "Tracked Rooms"
                BottomNavItem.Slots.route -> "My Slots"
                BottomNavItem.Activity.route -> {
                    when (val filter = historyFilter) {
                        HistoryFilter.Active -> "Active Rooms"
                        HistoryFilter.Archived -> "Archived Rooms"
                        HistoryFilter.All -> "All History"
                        is HistoryFilter.Specific -> roomNames[filter.roomId] ?: "Room History"
                    }
                }
                BottomNavItem.Profile.route -> "Profile"
                else -> "Archipelago Tracker"
            }

            TopAppBar(
                title = { Text(titleText) },
                actions = {
                    if (currentRoute == BottomNavItem.Rooms.route) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.padding(end = 16.dp) // Right margin
                        ) {

                            val profile = userProfile
                            val isCheeseConnected = profile?.is_cheese_connected == true

                            // 1. AVATAR
                            if (profile != null && !profile.is_guest) {
                                if (profile.avatar_url != null) {
                                    AsyncImage(
                                        model = profile.avatar_url,
                                        contentDescription = "Profile",
                                        modifier = Modifier
                                            .size(32.dp)
                                            .clip(CircleShape)
                                            .border(1.dp, MaterialTheme.colorScheme.outlineVariant, CircleShape),
                                        contentScale = ContentScale.Crop
                                    )
                                } else {
                                    Icon(
                                        Icons.Default.AccountCircle,
                                        null,
                                        modifier = Modifier.size(32.dp),
                                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                                Spacer(modifier = Modifier.width(8.dp))
                            }

                            // 2. CHEESE ICONS
                            if (isCheeseConnected) {

                                Text(
                                    text = "🧀",
                                    style = MaterialTheme.typography.titleMedium,
                                    modifier = Modifier
                                        .clickable { uriHandler.openUri("https://cheesetrackers.theincrediblewheelofchee.se/") }
                                        .padding(1.dp) // Small hit target padding
                                )

                                Spacer(modifier = Modifier.width(8.dp))

                                // Sync Button (Direct Clickable Icon)
                                val infiniteTransition = rememberInfiniteTransition(label = "spin")
                                val angle by infiniteTransition.animateFloat(
                                    initialValue = 0f,
                                    targetValue = 360f,
                                    animationSpec = infiniteRepeatable(
                                        animation = tween(1000, easing = LinearEasing)
                                    ),
                                    label = "spinAngle"
                                )

                                Icon(
                                    imageVector = Icons.Default.Refresh,
                                    contentDescription = "Sync",
                                    modifier = Modifier
                                        .size(24.dp) // Standard Icon size
                                        .then(if (isSyncingCheese) Modifier.rotate(angle) else Modifier)
                                        .clickable(enabled = !isSyncingCheese) {
                                            roomsViewModel.refreshAll(isCheeseConnected = true, forceCheeseSync = true)
                                        }
                                        .padding(2.dp) // Minimal padding
                                )
                            }
                        }
                    }
                }
            )
        },

        bottomBar = {
            NavigationBar {
                items.forEach { item ->
                    NavigationBarItem(
                        icon = { Icon(item.icon, contentDescription = item.label) },
                        label = { Text(item.label) },
                        selected = currentRoute == item.route,
                        onClick = {
                            bottomNavController.navigate(item.route) {
                                popUpTo(bottomNavController.graph.findStartDestination().id) { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        }
                    )
                }
            }
        },
        floatingActionButton = {
            Column(horizontalAlignment = Alignment.End) {
                if (isAnySnoozeActive) {
                    ExtendedFloatingActionButton(
                        text = {
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
            modifier = Modifier.padding(innerPadding)
        ) {
            composable(BottomNavItem.Rooms.route) {
                RoomsScreen(
                    roomsViewModel = roomsViewModel,
                    userViewModel = userViewModel,
                    onRoomClick = { roomId, _ ->
                        historyViewModel.loadHistoryFor(roomId, null, null)
                        bottomNavController.navigate(BottomNavItem.Activity.route) {
                            popUpTo(bottomNavController.graph.findStartDestination().id) { saveState = true }
                            launchSingleTop = true
                            restoreState = true
                        }
                    },
                    onManageSlotsClick = onNavigateToPlayers,
                )
            }
            composable(BottomNavItem.Slots.route) {
                SlotsScreen(
                    userViewModel = userViewModel,
                    onSlotClick = onNavigateToSlotDetail
                )
            }
            composable(BottomNavItem.Activity.route) {
                ActivityFeedScreen(
                    userViewModel = userViewModel,
                    historyViewModel = historyViewModel,
                    onNavigateToSlotDetail = onNavigateToSlotDetail
                )
            }
            composable(BottomNavItem.Profile.route) {
                ProfileScreen(
                    userViewModel = userViewModel,
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