package com.jones.aptracker.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jones.aptracker.network.Player // Keep this import
import kotlinx.coroutines.delay

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlayersScreen(
    roomId: Int,
    roomAlias: String,
    onSave: () -> Unit, // This callback is triggered *after* successful save
    onHistoryClick: () -> Unit,
    playersViewModel: PlayersViewModel = viewModel()
) {
    // Fetch players when the screen is first composed or roomId changes
    LaunchedEffect(key1 = roomId) {
        playersViewModel.fetchPlayers(roomId)
    }

    val snackbarHostState = remember { SnackbarHostState() }

    // Show confirmation snackbar when the ViewModel indicates success
    LaunchedEffect(playersViewModel.showSaveConfirmation.value) {
        if (playersViewModel.showSaveConfirmation.value) {
            snackbarHostState.showSnackbar("Selections Saved!")
            delay(1500) // Keep message for 1.5 seconds
            playersViewModel.showSaveConfirmation.value = false // Reset the flag
            onSave() // Navigate back or perform other action after save
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(hostState = snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text(roomAlias) },
                actions = {
                    IconButton(onClick = onHistoryClick) {
                        Icon(Icons.Default.History, contentDescription = "View History")
                    }
                }
            )
        },
        floatingActionButton = {
            // Disable FAB while loading to prevent double clicks
            FloatingActionButton(
                onClick = {
                    if (!playersViewModel.isLoading.value) { // Prevent saving while already saving/loading
                        playersViewModel.saveSelections(roomId)
                    }
                }
            ) {
                // Show progress indicator inside FAB if saving
                if (playersViewModel.isLoading.value && !playersViewModel.showSaveConfirmation.value) {
                    CircularProgressIndicator(modifier = Modifier.size(24.dp))
                } else {
                    Text("Save", modifier = Modifier.padding(horizontal = 16.dp))
                }
            }
        }
    ) { innerPadding ->
        Column(modifier = Modifier.padding(innerPadding)) {
            // Search Bar remains the same
            TextField(
                value = playersViewModel.searchQuery.value,
                onValueChange = { playersViewModel.onSearchQueryChanged(it) },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                label = { Text("Search by Player or Game") },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                singleLine = true
            )

            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center // Center loading/error messages
            ) {
                // Show loading indicator when initially fetching players
                if (playersViewModel.isLoading.value && playersViewModel.allPlayers.value.isEmpty()) {
                    CircularProgressIndicator()
                } else if (playersViewModel.errorMessage.value != null) {
                    // Show error message if fetching or saving failed
                    Text(
                        text = playersViewModel.errorMessage.value!!,
                        modifier = Modifier.padding(16.dp),
                        color = Color.Red
                    )
                } else {
                    // Player List
                    LazyColumn(modifier = Modifier.fillMaxSize()) {
                        // Use the filtered list from the ViewModel
                        items(playersViewModel.filteredPlayers, key = { it.slot_id }) { player ->
                            // Get the current checked state from the ViewModel's map
                            val isChecked = playersViewModel.isPlayerChecked(player)
                            // Determine if the player is done (using game name for now)
                            val isPlayerDone = player.game == "Archipelago"

                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    // Make row clickable only if player is not done
                                    .clickable(enabled = !isPlayerDone) {
                                        // Toggle the selection in the ViewModel's map
                                        playersViewModel.onPlayerSelectionChanged(player.slot_id, !isChecked)
                                    }
                                    .padding(horizontal = 16.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Checkbox(
                                    checked = isChecked,
                                    onCheckedChange = { isSelected ->
                                        // Update the ViewModel's map when checkbox changes
                                        playersViewModel.onPlayerSelectionChanged(player.slot_id, isSelected)
                                    },
                                    // Disable checkbox if player is done
                                    enabled = !isPlayerDone
                                )
                                Spacer(Modifier.width(16.dp))
                                Column {
                                    Text(
                                        text = player.name ?: "Unnamed Player",
                                        // Gray out text if player is done or name is missing
                                        color = if (isPlayerDone || player.name == null) Color.Gray else LocalContentColor.current
                                    )
                                    Text(
                                        text = if (isPlayerDone) "Finished" else player.game ?: "Unknown Game",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = Color.Gray
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}