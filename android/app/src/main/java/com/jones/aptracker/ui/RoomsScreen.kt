package com.jones.aptracker.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.History
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.accompanist.swiperefresh.SwipeRefresh
import com.google.accompanist.swiperefresh.rememberSwipeRefreshState
import com.jones.aptracker.R
import com.jones.aptracker.network.Room
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.ui.draw.clip
import coil.compose.AsyncImage
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RoomsScreen(
    roomsViewModel: RoomsViewModel = viewModel(),
    userViewModel: UserViewModel = viewModel(),
    onRoomClick: (Int, String) -> Unit,
    onHistoryClick: () -> Unit,
    onLogoutClick: () -> Unit
) {
    val rooms by roomsViewModel.rooms.collectAsState()
    val isLoading by roomsViewModel.isLoading.collectAsState()

    var showAddDialog by remember { mutableStateOf(false) }
    var roomToDelete by remember { mutableStateOf<Room?>(null) }
    var roomToEdit by remember { mutableStateOf<Room?>(null) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Tracked Rooms") },
                actions = {
                    ProfileMenu(
                        userViewModel = userViewModel,
                        onHistoryClick = onHistoryClick,
                        onLogoutClick = onLogoutClick
                    )
                }
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { showAddDialog = true }) {
                Icon(Icons.Default.Add, contentDescription = "Add Room")
            }
        }
    ) { innerPadding ->
        SwipeRefresh(
            state = rememberSwipeRefreshState(isRefreshing = isLoading),
            onRefresh = { roomsViewModel.fetchRooms() },
            modifier = Modifier.padding(innerPadding)
        ) {
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center
            ) {
                if (isLoading && rooms.isEmpty()) {
                    CircularProgressIndicator()
                } else if (rooms.isEmpty()) {
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .verticalScroll(rememberScrollState())
                    ) {
                        Text(
                            text = "No rooms found. Tap the '+' to add a room.",
                            modifier = Modifier.align(Alignment.Center)
                        )
                    }
                } else {
                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(8.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        item {
                            Image(
                                painter = painterResource(id = R.drawable.archipelago_tracker_banner),
                                contentDescription = "Archipelago Tracker Banner",
                                modifier = Modifier
                                    .fillMaxWidth(0.95f)
                                    .padding(bottom = 8.dp)
                                    .clip(RoundedCornerShape(8.dp)),
                                contentScale = ContentScale.FillWidth
                            )
                        }

                        items(rooms) { room ->
                            Card(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 4.dp)
                                    .clickable { onRoomClick(room.id, room.alias) },
                                elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
                            ) {
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(start = 16.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Icon(
                                        imageVector = getIconByName(room.icon_name),
                                        contentDescription = "Room Icon",
                                        modifier = Modifier.size(24.dp)
                                    )
                                    Spacer(Modifier.width(16.dp))
                                    Column(
                                        modifier = Modifier
                                            .weight(1f)
                                            .padding(vertical = 12.dp)
                                    ) {
                                        Text(
                                            text = room.alias,
                                            style = MaterialTheme.typography.titleMedium
                                        )
                                        Spacer(modifier = Modifier.height(4.dp))
                                        Text(
                                            text = room.host ?: "Connecting...",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = Color.Gray
                                        )
                                        Text(
                                            text = "${room.tracked_slots_count} / ${room.total_slots_count} slots tracked",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = Color.Gray
                                        )
                                    }
                                    IconButton(onClick = { roomToEdit = room }) {
                                        Icon(Icons.Default.Edit, contentDescription = "Edit Room Alias")
                                    }
                                    IconButton(onClick = { roomToDelete = room }) {
                                        Icon(Icons.Default.Delete, contentDescription = "Delete Room")
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        if (showAddDialog) {
            AddRoomDialog(
                onDismiss = { showAddDialog = false },
                onAdd = { roomUrl, alias, iconName ->
                    roomsViewModel.addRoom(roomUrl, alias, iconName)
                    showAddDialog = false
                }
            )
        }

        roomToEdit?.let { room ->
            EditRoomDialog(
                room = room,
                onDismiss = { roomToEdit = null },
                onConfirm = { newAlias, newIconName ->
                    roomsViewModel.updateRoom(room.id, newAlias, newIconName)
                    roomToEdit = null
                }
            )
        }

        roomToDelete?.let { room ->
            AlertDialog(
                onDismissRequest = { roomToDelete = null },
                title = { Text("Delete Room") },
                text = { Text("Are you sure you want to stop tracking '${room.alias}'?") },
                confirmButton = {
                    TextButton(onClick = {
                        roomsViewModel.deleteRoom(room.id)
                        roomToDelete = null
                    }) {
                        Text("Delete")
                    }
                },
                dismissButton = {
                    TextButton(onClick = { roomToDelete = null }) {
                        Text("Cancel")
                    }
                }
            )
        }
    }
}


@Composable
fun AddRoomDialog(onDismiss: () -> Unit, onAdd: (String, String, String) -> Unit) {
    var roomUrl by remember { mutableStateOf("") }
    var alias by remember { mutableStateOf("") }
    var selectedIconName by remember { mutableStateOf("default_icon") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add New Room") },
        text = {
            Column {
                TextField(
                    value = roomUrl,
                    onValueChange = { roomUrl = it },
                    label = { Text("Room URL") },
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(8.dp))
                TextField(
                    value = alias,
                    onValueChange = { alias = it },
                    label = { Text("Alias") },
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(16.dp))
                Text("Select Icon", style = MaterialTheme.typography.labelMedium)
                Spacer(Modifier.height(8.dp))
                LazyRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(AppIcons.allIcons.toList()) { (name, icon) ->
                        val isSelected = name == selectedIconName
                        Box(
                            modifier = Modifier
                                .size(40.dp)
                                .clip(CircleShape)
                                .background(if (isSelected) MaterialTheme.colorScheme.primaryContainer else Color.Transparent)
                                .border(1.dp, if(isSelected) MaterialTheme.colorScheme.primary else Color.Gray, CircleShape)
                                .clickable { selectedIconName = name },
                            contentAlignment = Alignment.Center
                        ) {
                            Icon(imageVector = icon, contentDescription = name)
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = { onAdd(roomUrl, alias, selectedIconName) },
                enabled = roomUrl.isNotBlank() && alias.isNotBlank()
            ) {
                Text("Add")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel")
            }
        }
    )
}

@Composable
fun EditRoomDialog(room: Room, onDismiss: () -> Unit, onConfirm: (String, String) -> Unit) {
    var alias by remember { mutableStateOf(room.alias) }
    var selectedIconName by remember { mutableStateOf(room.icon_name) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Edit Room") },
        text = {
            Column {
                TextField(
                    value = alias,
                    onValueChange = { alias = it },
                    label = { Text("New Alias") },
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(16.dp))
                Text("Select Icon", style = MaterialTheme.typography.labelMedium)
                Spacer(Modifier.height(8.dp))
                LazyRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(AppIcons.allIcons.toList()) { (name, icon) ->
                        val isSelected = name == selectedIconName
                        Box(
                            modifier = Modifier
                                .size(40.dp)
                                .clip(CircleShape)
                                .background(if (isSelected) MaterialTheme.colorScheme.primaryContainer else Color.Transparent)
                                .border(1.dp, if(isSelected) MaterialTheme.colorScheme.primary else Color.Gray, CircleShape)
                                .clickable { selectedIconName = name },
                            contentAlignment = Alignment.Center
                        ) {
                            Icon(imageVector = icon, contentDescription = name)
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = { onConfirm(alias, selectedIconName) },
                enabled = alias.isNotBlank()
            ) {
                Text("Save")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel")
            }
        }
    )
}

@Composable
fun ProfileMenu(
    userViewModel: UserViewModel,
    onHistoryClick: () -> Unit,
    onLogoutClick: () -> Unit
) {
    val userProfile by userViewModel.userProfile.collectAsState()
    var menuExpanded by remember { mutableStateOf(false) }

    Box {
        IconButton(onClick = { menuExpanded = true }) {
            if (userProfile?.avatar_url != null) {
                AsyncImage(
                    model = userProfile?.avatar_url,
                    contentDescription = "User Profile",
                    modifier = Modifier.size(32.dp).clip(CircleShape),
                    contentScale = ContentScale.Crop
                )
            } else {
                // Fallback icon if the image is loading or unavailable
                Icon(Icons.Default.MoreVert, contentDescription = "Menu")
            }
        }
        DropdownMenu(
            expanded = menuExpanded,
            onDismissRequest = { menuExpanded = false }
        ) {
            userProfile?.discord_username?.let {
                DropdownMenuItem(
                    text = { Text("Logged in as $it", style = MaterialTheme.typography.labelMedium) },
                    onClick = { },
                    enabled = false // Not clickable
                )
                Divider()
            }
            DropdownMenuItem(
                text = { Text("Item History") },
                onClick = {
                    onHistoryClick()
                    menuExpanded = false
                }
            )
            DropdownMenuItem(
                text = { Text("Log Out") },
                onClick = {
                    onLogoutClick()
                    menuExpanded = false
                }
            )
        }
    }
}