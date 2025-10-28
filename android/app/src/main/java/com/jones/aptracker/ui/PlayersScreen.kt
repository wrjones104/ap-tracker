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
import com.jones.aptracker.network.Player
import kotlinx.coroutines.delay

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlayersScreen(roomId: Int, roomAlias: String, onSave: () -> Unit, onHistoryClick: () -> Unit, playersViewModel: PlayersViewModel = viewModel()) {
    LaunchedEffect(key1 = roomId) {
        playersViewModel.fetchPlayers(roomId)
    }

    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(playersViewModel.showSaveConfirmation.value) {
        if (playersViewModel.showSaveConfirmation.value) {
            snackbarHostState.showSnackbar("Selections Saved!")
            delay(1500)
            playersViewModel.showSaveConfirmation.value = false
            onSave()
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
            FloatingActionButton(onClick = {
                playersViewModel.saveSelections(roomId)
            }) {
                Text("Save", modifier = Modifier.padding(horizontal = 16.dp))
            }
        }
    ) { innerPadding ->
        Column(modifier = Modifier.padding(innerPadding)) {
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
                contentAlignment = Alignment.Center
            ) {
                if (playersViewModel.isLoading.value) {
                    CircularProgressIndicator()
                } else if (playersViewModel.errorMessage.value != null) {
                    Text(
                        text = playersViewModel.errorMessage.value!!,
                        modifier = Modifier.padding(16.dp),
                        color = Color.Red
                    )
                } else {
                    LazyColumn(modifier = Modifier.fillMaxSize()) {
                        items(playersViewModel.filteredPlayers) { player ->
                            val isChecked = playersViewModel.isPlayerChecked(player)
                            val isPlayerDone = player.game == "Archipelago"

                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable(enabled = !isPlayerDone) {
                                        playersViewModel.onPlayerSelectionChanged(player.slot_id, !isChecked)
                                    }
                                    .padding(horizontal = 16.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Checkbox(
                                    checked = isChecked,
                                    onCheckedChange = { isSelected ->
                                        playersViewModel.onPlayerSelectionChanged(player.slot_id, isSelected)
                                    },
                                    enabled = !isPlayerDone
                                )
                                Spacer(Modifier.width(16.dp))
                                Column {
                                    Text(
                                        // **THE FIX**: Provide a default value if name is null
                                        text = player.name ?: "Unnamed Player",
                                        color = if (isPlayerDone || player.name == null) Color.Gray else Color.Unspecified
                                    )
                                    Text(
                                        // **THE FIX**: Provide a default value if game is null
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