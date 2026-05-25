package com.jones.aptracker.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlayersScreen(
    roomId: Int,
    roomAlias: String,
    onSave: () -> Unit,
    userViewModel: UserViewModel,
    historyViewModel: HistoryViewModel,
    playersViewModel: PlayersViewModel = viewModel()
) {
    LaunchedEffect(key1 = roomId) {
        playersViewModel.fetchPlayers(roomId)
    }

    val snackbarHostState = remember { SnackbarHostState() }

    val errorMessage by playersViewModel.errorMessage.collectAsState()

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
            launch { snackbarHostState.showSnackbar("Selections Saved!") }

            // Instantly refresh ViewModels to prevent stale cache in other screens
            userViewModel.fetchTrackedSlots()
            historyViewModel.refreshAllHistory()

            playersViewModel.showSaveConfirmation.value = false
            onSave()
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
                modifier = Modifier.fillMaxWidth().weight(1f),
                contentAlignment = Alignment.Center
            ) {
                if (playersViewModel.isLoading.value) {
                    CircularProgressIndicator()
                } else {
                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(bottom = 80.dp)
                    ) {
                        items(
                            items = playersViewModel.filteredPlayers,
                            key = { it.slot_id }
                        ) { player ->
                            val isChecked = playersViewModel.isPlayerChecked(player)
                            val isPlayerDone = player.is_finished

                            Card(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 16.dp, vertical = 4.dp),
                                shape = MaterialTheme.shapes.medium,
                            ) {
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clickable {
                                            playersViewModel.onPlayerSelectionChanged(player.slot_id, !isChecked)
                                        }
                                        .padding(horizontal = 16.dp, vertical = 8.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Checkbox(
                                        checked = isChecked,
                                        onCheckedChange = null,
                                        enabled = true
                                    )
                                    Spacer(Modifier.width(16.dp))
                                    Column {
                                        val originalName = player.name ?: "Unnamed"
                                        val displayName = if (!player.alias.isNullOrBlank()) {
                                            "${player.alias} ($originalName)"
                                        } else {
                                            originalName
                                        }

                                        val statusPrefix = if (isPlayerDone) "🏁 " else ""

                                        Text(
                                            text = statusPrefix + displayName,
                                            color = if (isPlayerDone) Color(0xFF0E8A0E) else Color.Unspecified
                                        )
                                        Text(
                                            text =  player.game ?: "Unknown Game",
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
}