package com.jones.aptracker.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jones.aptracker.network.TrackedSlotDetail
import com.jones.aptracker.network.UserProfile

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SlotOverridesScreen(
    userViewModel: UserViewModel = viewModel(),
    onBackClick: () -> Unit
) {
    val trackedSlotsByRoom by userViewModel.trackedSlotsByRoom.collectAsState()
    val userProfile by userViewModel.userProfile.collectAsState()

    var editingSlot by remember { mutableStateOf<Pair<Int, TrackedSlotDetail>?>(null) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Per-Slot Overrides") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        if (trackedSlotsByRoom.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "You are not tracking any slots yet.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(horizontal = 16.dp)
            ) {
                item {
                    Text(
                        text = "Customize notifications for specific player slots here. These settings override your global defaults.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 16.dp)
                    )
                }

                trackedSlotsByRoom.forEach { roomData ->
                    item(key = "header_${roomData.room_db_id}") {
                        RoomHeader(alias = roomData.room_alias)
                    }

                    items(
                        items = roomData.tracked_slots,
                        key = { slot -> "slot_${roomData.room_db_id}_${slot.slot_id}" }
                    ) { slot ->
                        SlotPreferenceItem(
                            slot = slot,
                            onClick = {
                                editingSlot = Pair(roomData.room_db_id, slot)
                            }
                        )
                    }

                    item(key = "spacer_${roomData.room_db_id}") {
                        Spacer(Modifier.height(16.dp))
                    }
                }
            }
        }
    }

    if (editingSlot != null && userProfile != null) {
        val (roomId, slotDetail) = editingSlot!!
        val sheetHeaderName = if (!slotDetail.player_alias.isNullOrBlank()) {
            "${slotDetail.player_alias} (${slotDetail.player_name})"
        } else {
            slotDetail.player_name
        }
        ModalBottomSheet(
            onDismissRequest = { editingSlot = null },
            sheetState = sheetState
        ) {
            SlotSettingsSheet(
                playerSlotId = slotDetail.slot_id,
                playerName = sheetHeaderName,
                currentProgression = slotDetail.notify_progression,
                currentUseful = slotDetail.notify_useful,
                currentHints = slotDetail.notify_hints,
                currentRemoteHints = slotDetail.notify_hints_remote_items,
                currentFinished = slotDetail.notify_finished,
                currentCondensed = slotDetail.use_condensed_messages,
                globalProfile = userProfile!!,
                onSave = { prog, use, hint, remote, finished, condensed ->
                    userViewModel.updateSlotPreferences(
                        roomId,
                        slotDetail.slot_id,
                        prog, use, hint, remote, finished,
                        condensed
                    )
                    editingSlot = null
                },
                onDismiss = { editingSlot = null }
            )
        }
    }
}

// --- HELPER COMPONENTS ---

@Composable
fun RoomHeader(alias: String) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            text = alias,
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.primary,
            modifier = Modifier.padding(top = 8.dp, bottom = 4.dp)
        )
        HorizontalDivider()
    }
}

@Composable
fun SlotPreferenceItem(
    slot: TrackedSlotDetail,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        val displayName = if (!slot.player_alias.isNullOrBlank()) {
            "${slot.player_alias} (${slot.player_name})"
        } else {
            slot.player_name
        }

        Text(
            text = displayName,
            style = MaterialTheme.typography.bodyLarge,
            modifier = Modifier.weight(1f)
        )
        Icon(
            Icons.Default.Settings,
            contentDescription = "Edit Slot",
            tint = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SlotSettingsSheet(
    playerSlotId: Int,
    playerName: String,
    currentProgression: Boolean?,
    currentUseful: Boolean?,
    currentHints: Boolean?,
    currentRemoteHints: Boolean?,
    currentFinished: Boolean?,
    currentCondensed: Boolean?,
    globalProfile: UserProfile,
    onSave: (Boolean?, Boolean?, Boolean?, Boolean?, Boolean?, Boolean?) -> Unit,
    onDismiss: () -> Unit
) {
    // Local state for the overrides (null means "Use Default")
    var progression by remember(playerSlotId) { mutableStateOf(currentProgression) }
    var useful by remember(playerSlotId) { mutableStateOf(currentUseful) }
    var hints by remember(playerSlotId) { mutableStateOf(currentHints) }
    var remoteHints by remember(playerSlotId) { mutableStateOf(currentRemoteHints) }
    var finished by remember(playerSlotId) { mutableStateOf(currentFinished) }
    var condensed by remember(playerSlotId) { mutableStateOf(currentCondensed) }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp)
            .navigationBarsPadding()
    ) {
        Text(
            text = "Notify Settings for $playerName",
            style = MaterialTheme.typography.titleLarge,
            modifier = Modifier.padding(bottom = 24.dp)
        )

        OverrideRow(
            title = "Progression Items",
            currentValue = progression,
            defaultValue = globalProfile.notify_progression_default,
            onValueChange = { progression = it }
        )
        Spacer(Modifier.height(16.dp))

        OverrideRow(
            title = "Useful Items",
            currentValue = useful,
            defaultValue = globalProfile.notify_useful_default,
            onValueChange = { useful = it }
        )
        Spacer(Modifier.height(16.dp))

        OverrideRow(
            title = "Hints in this World",
            currentValue = hints,
            defaultValue = globalProfile.notify_hints_default,
            onValueChange = { hints = it }
        )
        Spacer(Modifier.height(16.dp))

        OverrideRow(
            title = "Hints for this Player's Items",
            currentValue = remoteHints,
            defaultValue = globalProfile.notify_hints_remote_items_default,
            onValueChange = { remoteHints = it }
        )
        Spacer(Modifier.height(16.dp))

        OverrideRow(
            title = "Finished",
            currentValue = finished,
            defaultValue = globalProfile.notify_finished_default,
            onValueChange = { finished = it }
        )
        Spacer(Modifier.height(16.dp))

        OverrideRow(
            title = "Condensed Messages",
            currentValue = condensed,
            defaultValue = globalProfile.use_condensed_messages_default,
            onValueChange = { condensed = it }
        )

        Spacer(Modifier.height(24.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.End
        ) {
            TextButton(onClick = onDismiss) { Text("Cancel") }
            Spacer(Modifier.width(8.dp))
            Button(onClick = {
                onSave(progression, useful, hints, remoteHints, finished, condensed)
            }) { Text("Save") }
        }
    }
}

/**
 * A clean row that handles the Title, the Toggle, and the "Reset" logic.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OverrideRow(
    title: String,
    currentValue: Boolean?,
    defaultValue: Boolean,
    onValueChange: (Boolean?) -> Unit
) {
    // Effective value is what the toggle should show (Actual OR Default)
    val effectiveValue = currentValue ?: defaultValue
    val isOverridden = currentValue != null

    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(text = title, style = MaterialTheme.typography.titleMedium)
                if (!isOverridden) {
                    Text(
                        text = "Using default (${if (defaultValue) "On" else "Off"})",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

            // Only show the Reset button if the user has actually changed this setting
            if (isOverridden) {
                TextButton(
                    onClick = { onValueChange(null) }, // Reset to null (Default)
                    modifier = Modifier.padding(end = 8.dp)
                ) {
                    Text("Reset")
                }
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

        // Simple 2-state toggle
        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
            val options = listOf("Off", "On")
            val selectedIndex = if (effectiveValue) 1 else 0

            options.forEachIndexed { index, label ->
                SegmentedButton(
                    selected = index == selectedIndex,
                    onClick = {
                        val newValue = (index == 1) // 0 -> false, 1 -> true
                        onValueChange(newValue)
                    },
                    shape = SegmentedButtonDefaults.itemShape(index = index, count = options.size)
                ) {
                    Text(label)
                }
            }
        }
    }
}