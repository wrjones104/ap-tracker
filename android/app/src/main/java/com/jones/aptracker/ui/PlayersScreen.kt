package com.jones.aptracker.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Flag
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
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
import com.jones.aptracker.network.Player
import com.jones.aptracker.network.TrackMode
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

                                        // Vector icon rather than a literal emoji: consistent
                                        // across devices and readable by screen readers, and it
                                        // distinguishes goaled from fully drained (issue #262).
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            if (isPlayerDone || player.has_all_checks == true) {
                                                val fullyDone = isPlayerDone && player.has_all_checks == true
                                                Icon(
                                                    imageVector = if (fullyDone) Icons.Filled.CheckCircle else Icons.Filled.Flag,
                                                    contentDescription = when {
                                                        fullyDone -> "Goaled, no items left to send"
                                                        isPlayerDone -> "Goaled"
                                                        else -> "No items left to send"
                                                    },
                                                    tint = Color(0xFF0E8A0E),
                                                    modifier = Modifier.size(16.dp)
                                                )
                                                Spacer(Modifier.width(4.dp))
                                            }
                                            Text(
                                                text = displayName,
                                                color = if (isPlayerDone) Color(0xFF0E8A0E) else Color.Unspecified
                                            )
                                        }
                                        Text(
                                            text =  player.game ?: "Unknown Game",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = Color.Gray
                                        )

                                        // The Playing/Watching choice only exists for
                                        // Cheese-linked rooms, and only once the slot is
                                        // actually selected -- an unchecked row has no mode.
                                        if (isChecked && playersViewModel.showsTrackMode(player)) {
                                            Spacer(Modifier.height(8.dp))
                                            TrackModeSelector(
                                                mode = playersViewModel.modeFor(player),
                                                claimLocked = playersViewModel.isClaimLocked(player),
                                                claimedBy = player.cheese_claim?.claimed_by,
                                                onModeSelected = { mode ->
                                                    playersViewModel.onTrackModeChanged(player, mode)
                                                }
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
}

/**
 * Playing vs Watching for one slot.
 *
 * Playing claims the slot on Cheese Tracker; Watching only sends alerts and
 * never writes to Cheese. When someone else already holds the slot, Playing is
 * disabled and the caption names the holder, so a claim that would collide is
 * never offered in the first place.
 *
 * The labels stay plain text: SegmentedButton already draws a check in its own
 * icon slot for the selected option, and adding a second icon inside the label
 * makes the two collide on narrow rows.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TrackModeSelector(
    mode: String,
    claimLocked: Boolean,
    claimedBy: String?,
    onModeSelected: (String) -> Unit
) {
    Column {
        SingleChoiceSegmentedButtonRow {
            SegmentedButton(
                selected = mode == TrackMode.PLAY,
                onClick = { onModeSelected(TrackMode.PLAY) },
                enabled = !claimLocked,
                shape = SegmentedButtonDefaults.itemShape(index = 0, count = 2)
            ) {
                Text("Playing", style = MaterialTheme.typography.labelMedium, maxLines = 1)
            }
            SegmentedButton(
                selected = mode == TrackMode.WATCH,
                onClick = { onModeSelected(TrackMode.WATCH) },
                shape = SegmentedButtonDefaults.itemShape(index = 1, count = 2)
            ) {
                Text("Watching", style = MaterialTheme.typography.labelMedium, maxLines = 1)
            }
        }

        Text(
            text = if (claimLocked) {
                if (claimedBy.isNullOrBlank()) {
                    "Claimed by someone else on Cheese Tracker"
                } else {
                    "Claimed by $claimedBy on Cheese Tracker"
                }
            } else if (mode == TrackMode.WATCH) {
                "Alerts only. Not claimed on Cheese Tracker."
            } else {
                "Claimed by you on Cheese Tracker."
            },
            style = MaterialTheme.typography.labelSmall,
            color = Color.Gray,
            modifier = Modifier.padding(top = 4.dp)
        )
    }
}
