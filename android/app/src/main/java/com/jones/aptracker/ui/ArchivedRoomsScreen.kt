package com.jones.aptracker.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Restore
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.accompanist.swiperefresh.SwipeRefresh
import com.google.accompanist.swiperefresh.rememberSwipeRefreshState
import com.jones.aptracker.network.Room

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ArchivedRoomsScreen(
    roomsViewModel: RoomsViewModel = viewModel(),
    onBackClick: () -> Unit
) {
    // Load archived rooms when screen opens
    LaunchedEffect(Unit) {
        roomsViewModel.fetchArchivedRooms()
    }

    val archivedRooms by roomsViewModel.archivedRooms.collectAsState()
    val isLoading by roomsViewModel.isLoadingArchived.collectAsState()
    val errorMessage by roomsViewModel.errorMessage.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(errorMessage) {
        errorMessage?.let {
            snackbarHostState.showSnackbar(it)
            roomsViewModel.clearErrorMessage()
        }
    }

    var roomToRestore by remember { mutableStateOf<Room?>(null) }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text("Archived Rooms") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        SwipeRefresh(
            state = rememberSwipeRefreshState(isRefreshing = isLoading),
            onRefresh = { roomsViewModel.fetchArchivedRooms() },
            modifier = Modifier.padding(padding)
        ) {
            if (archivedRooms.isEmpty() && !isLoading) {
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(
                        "No archived rooms found.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            } else {
                LazyColumn(
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxSize()
                ) {
                    items(archivedRooms) { room ->
                        ArchivedRoomCard(
                            room = room,
                            onRestoreClick = { roomToRestore = room }
                        )
                    }
                }
            }
        }
    }

    // Restore Confirmation Dialog
    if (roomToRestore != null) {
        AlertDialog(
            onDismissRequest = { roomToRestore = null },
            title = { Text("Restore Room?") },
            text = { Text("Do you want to move '${roomToRestore?.alias}' back to your active list?") },
            confirmButton = {
                Button(onClick = {
                    roomToRestore?.let { roomsViewModel.unarchiveRoom(it.id) }
                    roomToRestore = null
                }) {
                    Text("Restore")
                }
            },
            dismissButton = {
                TextButton(onClick = { roomToRestore = null }) {
                    Text("Cancel")
                }
            }
        )
    }
}

@Composable
fun ArchivedRoomCard(
    room: Room,
    onRestoreClick: () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = getIconByName(room.icon_name),
                contentDescription = null,
                modifier = Modifier.size(24.dp),
                tint = Color.Gray // Grayed out to indicate archive
            )
            Spacer(modifier = Modifier.width(16.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = room.alias,
                    style = MaterialTheme.typography.titleMedium,
                    color = Color.Gray // Grayed out text
                )
                Text(
                    text = room.host ?: "Unknown Host",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.Gray
                )
            }
            IconButton(onClick = onRestoreClick) {
                Icon(Icons.Default.Restore, contentDescription = "Restore")
            }
        }
    }
}