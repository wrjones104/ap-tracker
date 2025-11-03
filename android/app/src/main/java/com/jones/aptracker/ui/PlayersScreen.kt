package com.jones.aptracker.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items // <-- IMPORT ADDED
import kotlinx.coroutines.launch
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration // <-- IMPORT ADDED
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState // <-- IMPORT ADDED
import androidx.compose.runtime.getValue // <-- IMPORT ADDED
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.delay

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlayersScreen(
    roomId: Int,
    roomAlias: String,
    onSave: () -> Unit,
    playersViewModel: PlayersViewModel = viewModel()
) {
    LaunchedEffect(key1 = roomId) {
        playersViewModel.fetchPlayers(roomId)
    }

    val snackbarHostState = remember { SnackbarHostState() }

    // --- NEW: Collect error message from StateFlow ---
    val errorMessage by playersViewModel.errorMessage.collectAsState()

    // --- NEW: Show error Snackbar ---
    LaunchedEffect(errorMessage) {
        if (errorMessage != null) {
            snackbarHostState.showSnackbar(
                message = errorMessage!!,
                duration = SnackbarDuration.Short
            )
            playersViewModel.clearErrorMessage()
        }
    }

    LaunchedEffect(playersViewModel.showSaveConfirmation.value) {
        if (playersViewModel.showSaveConfirmation.value) {
            // Show the snackbar, but don't wait for it
            launch { snackbarHostState.showSnackbar("Selections Saved!") }

            // Immediately reset the state and navigate
            playersViewModel.showSaveConfirmation.value = false
            onSave() // This will now navigate right away
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(hostState = snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text(roomAlias) },
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
                modifier = Modifier.fillMaxSize().weight(1f),
                contentAlignment = Alignment.Center
            ) {
                if (playersViewModel.isLoading.value) {
                    CircularProgressIndicator()
                } else {
                    // --- CHANGED: Removed the error text from here ---
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
                                        text = player.name ?: "Unnamed Player",
                                        color = if (isPlayerDone || player.name == null) Color.Gray else Color.Unspecified
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