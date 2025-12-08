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
            text = "Notify Settings for $playerName (Slot $playerSlotId)",
            style = MaterialTheme.typography.titleLarge,
            modifier = Modifier.padding(bottom = 16.dp)
        )

        Text("Progression Items", style = MaterialTheme.typography.titleMedium)
        PreferenceToggle(
            selectedValue = progression,
            globalDefault = globalProfile.notify_progression_default,
            onValueChanged = { progression = it }
        )
        Spacer(Modifier.height(16.dp))

        Text("Useful Items", style = MaterialTheme.typography.titleMedium)
        PreferenceToggle(
            selectedValue = useful,
            globalDefault = globalProfile.notify_useful_default,
            onValueChanged = { useful = it }
        )
        Spacer(Modifier.height(16.dp))

        Text("Hints in this World", style = MaterialTheme.typography.titleMedium)
        PreferenceToggle(
            selectedValue = hints,
            globalDefault = globalProfile.notify_hints_default,
            onValueChanged = { hints = it }
        )
        Spacer(Modifier.height(16.dp))

        Text("Hints for this Player's Items", style = MaterialTheme.typography.titleMedium)
        PreferenceToggle(
            selectedValue = remoteHints,
            globalDefault = globalProfile.notify_hints_remote_items_default,
            onValueChanged = { remoteHints = it }
        )

        Spacer(Modifier.height(16.dp))

        Text("Finished", style = MaterialTheme.typography.titleMedium)
        PreferenceToggle(
            selectedValue = finished,
            globalDefault = globalProfile.notify_finished_default,
            onValueChanged = { finished = it }
        )

        Spacer(Modifier.height(16.dp))

        Text("Condensed Messages", style = MaterialTheme.typography.titleMedium)
        PreferenceToggle(
            selectedValue = condensed,
            globalDefault = globalProfile.use_condensed_messages_default,
            onValueChanged = { condensed = it }
        )

        Spacer(Modifier.height(24.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.End
        ) {
            TextButton(onClick = onDismiss) {
                Text("Cancel")
            }
            Spacer(Modifier.width(8.dp))
            Button(
                onClick = {
                    onSave(progression, useful, hints, remoteHints, finished, condensed)
                }
            ) {
                Text("Save")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PreferenceToggle(
    selectedValue: Boolean?,
    globalDefault: Boolean,
    onValueChanged: (Boolean?) -> Unit
) {
    val items = listOf("Off", "Default", "On")
    val selectedIndex = when (selectedValue) {
        null -> 1
        false -> 0
        true -> 2
    }
    val globalDefaultText = if (globalDefault) "(On)" else "(Off)"

    SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
        items.forEachIndexed { index, label ->
            SegmentedButton(
                selected = index == selectedIndex,
                onClick = {
                    val newValue = when (index) {
                        0 -> false
                        1 -> null
                        2 -> true
                        else -> null
                    }
                    onValueChanged(newValue)
                },
                shape = SegmentedButtonDefaults.itemShape(index = index, count = items.size)
            ) {
                Text(if (label == "Default") "Default $globalDefaultText" else label)
            }
        }
    }
}