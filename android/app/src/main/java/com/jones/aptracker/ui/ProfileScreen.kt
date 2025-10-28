package com.jones.aptracker.ui

import androidx.compose.foundation.clickable // <-- Added missing import
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Settings // <-- Added missing import
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jones.aptracker.network.RoomWithTrackedSlots
import com.jones.aptracker.network.TrackedSlotDetail
import com.jones.aptracker.network.UserProfile

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(
    userViewModel: UserViewModel = viewModel(),
    onBackClick: () -> Unit
) {
    val userProfile by userViewModel.userProfile.collectAsState()
    val trackedSlotsByRoom by userViewModel.trackedSlotsByRoom.collectAsState()

    var editingSlot by remember { mutableStateOf<Pair<Int, TrackedSlotDetail>?>(null) } // Pair(roomId, slotDetail)
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    if (editingSlot != null && userProfile != null) {
        val (roomId, slotDetail) = editingSlot!!
        ModalBottomSheet(
            onDismissRequest = { editingSlot = null },
            sheetState = sheetState
        ) {
            SlotSettingsSheet( // Reusing the sheet composable
                playerSlotId = slotDetail.slot_id,
                playerName = slotDetail.player_name,
                currentProgression = slotDetail.notify_progression,
                currentUseful = slotDetail.notify_useful,
                currentHints = slotDetail.notify_hints,
                globalProfile = userProfile!!,
                onSave = { prog, use, hint ->
                    userViewModel.updateSlotPreferences(roomId, slotDetail.slot_id, prog, use, hint)
                    editingSlot = null // Close sheet on save
                },
                onDismiss = { editingSlot = null } // Close sheet on dismiss
            )
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Settings") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp)
        ) {
            item {
                Text(
                    text = "Global Notification Defaults",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(vertical = 16.dp)
                )
            }
            item {
                userProfile?.let { profile ->
                    Column {
                        // Using the corrected NotificationToggle below
                        NotificationToggle(
                            text = "Progression Items",
                            checked = profile.notify_progression_default,
                            onCheckedChange = {
                                userViewModel.updateGlobalPreferences(progression = it)
                            }
                        )
                        NotificationToggle(
                            text = "Useful Items",
                            checked = profile.notify_useful_default,
                            onCheckedChange = {
                                userViewModel.updateGlobalPreferences(useful = it)
                            }
                        )
                        NotificationToggle(
                            text = "Hints",
                            checked = profile.notify_hints_default,
                            onCheckedChange = {
                                userViewModel.updateGlobalPreferences(hints = it)
                            }
                        )
                    }
                } ?: run {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 16.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator()
                    }
                }
            }
            item {
                Divider(modifier = Modifier.padding(vertical = 16.dp))
            }

            item {
                Text(
                    text = "Per-Slot Notification Overrides",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(bottom = 8.dp)
                )
            }

            if (trackedSlotsByRoom.isEmpty()) {
                item {
                    Text(
                        text = "You are not tracking any slots.",
                        modifier = Modifier.padding(vertical = 16.dp),
                        style = MaterialTheme.typography.bodyMedium
                    )
                }
            } else {
                trackedSlotsByRoom.forEach { roomData ->
                    item {
                        RoomHeader(alias = roomData.room_alias)
                    }
                    items(roomData.tracked_slots, key = { it.slot_id }) { slot ->
                        SlotPreferenceItem(
                            slot = slot,
                            onClick = {
                                editingSlot = Pair(roomData.room_db_id, slot)
                            }
                        )
                    }
                    item {
                        Spacer(Modifier.height(16.dp))
                    }
                }
            }
            item {
                Spacer(Modifier.height(16.dp))
            }
        }
    }
}

// --- CORRECTED Helper Composable for Global Toggles ---
@Composable
private fun NotificationToggle(
    text: String, // Added parameter
    checked: Boolean, // Added parameter
    onCheckedChange: (Boolean) -> Unit // Added parameter
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(text, style = MaterialTheme.typography.bodyLarge) // Use parameter
        Switch(
            checked = checked, // Use parameter
            onCheckedChange = onCheckedChange // Use parameter
        )
    }
}

// --- Helper Composable for Room Headers (Unchanged but verified) ---
@Composable
fun RoomHeader(alias: String) {
    Text(
        text = alias,
        style = MaterialTheme.typography.titleSmall,
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp)
    )
    Divider()
}

// --- Helper Composable for Each Slot Item (Unchanged but verified) ---
@Composable
fun SlotPreferenceItem(
    slot: TrackedSlotDetail,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick) // clickable import added
            .padding(vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = slot.player_name,
            style = MaterialTheme.typography.bodyLarge,
            modifier = Modifier.weight(1f)
        )
        Icon(
            Icons.Default.Settings, // Settings import added
            contentDescription = "Edit Slot ${slot.slot_id}",
            tint = MaterialTheme.colorScheme.primary
        )
    }
}


// --- Bottom Sheet Composable (Unchanged but verified) ---
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SlotSettingsSheet(
    playerSlotId: Int,
    playerName: String,
    currentProgression: Boolean?,
    currentUseful: Boolean?,
    currentHints: Boolean?,
    globalProfile: UserProfile,
    onSave: (prog: Boolean?, use: Boolean?, hint: Boolean?) -> Unit,
    onDismiss: () -> Unit
) {
    var progression by remember(playerSlotId) { mutableStateOf(currentProgression) }
    var useful by remember(playerSlotId) { mutableStateOf(currentUseful) }
    var hints by remember(playerSlotId) { mutableStateOf(currentHints) }

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
        // Using corrected PreferenceToggle below
        PreferenceToggle(
            selectedValue = progression,
            globalDefault = globalProfile.notify_progression_default,
            onValueChanged = { progression = it } // 'it' is valid here
        )
        Spacer(Modifier.height(16.dp))

        Text("Useful Items", style = MaterialTheme.typography.titleMedium)
        PreferenceToggle(
            selectedValue = useful,
            globalDefault = globalProfile.notify_useful_default,
            onValueChanged = { useful = it }
        )
        Spacer(Modifier.height(16.dp))

        Text("Hints", style = MaterialTheme.typography.titleMedium)
        PreferenceToggle(
            selectedValue = hints,
            globalDefault = globalProfile.notify_hints_default,
            onValueChanged = { hints = it }
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
            Button(onClick = { onSave(progression, useful, hints) }) {
                Text("Save")
            }
        }
    }
}

// --- CORRECTED Helper Composable for 3-state Toggle ---
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PreferenceToggle(
    selectedValue: Boolean?, // Added parameter
    globalDefault: Boolean, // Added parameter
    onValueChanged: (Boolean?) -> Unit // Added parameter
) {
    val items = listOf("Off", "Default", "On")
    val selectedIndex = when (selectedValue) {
        null -> 1
        false -> 0
        true -> 2
        // else branch not needed because Boolean? only has 3 states
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
                        else -> null // Added else branch to satisfy compiler
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