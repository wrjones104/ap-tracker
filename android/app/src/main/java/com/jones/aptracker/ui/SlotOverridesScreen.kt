package com.jones.aptracker.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
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

    // 1. Create a filtered list of active rooms
    val activeRooms = remember(trackedSlotsByRoom) {
        trackedSlotsByRoom.filter { !it.is_archived }
    }

    val errorMessage by userViewModel.errorMessage.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    // State for the bottom sheet
    var selectedSlotRoomId by remember { mutableStateOf<Int?>(null) }
    var selectedSlotDetail by remember { mutableStateOf<TrackedSlotDetail?>(null) }

    LaunchedEffect(errorMessage) {
        errorMessage?.let {
            snackbarHostState.showSnackbar(it)
            userViewModel.clearErrorMessage()
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text("Slot Overrides") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        if (activeRooms.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                contentAlignment = Alignment.Center
            ) {
                Text("No active tracked slots found.")
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(top = padding.calculateTopPadding())
            ) {
                items(activeRooms) { room ->
                    // Room Header
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            imageVector = getIconByName(room.icon_name),
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(24.dp)
                        )
                        Spacer(Modifier.width(12.dp))
                        Text(
                            text = room.room_alias,
                            style = MaterialTheme.typography.titleMedium,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }

                    // Slots List
                    room.tracked_slots.forEach { slot ->
                        SlotOverrideItem(
                            slot = slot,
                            onClick = {
                                selectedSlotRoomId = room.room_db_id
                                selectedSlotDetail = slot
                            }
                        )
                        HorizontalDivider(modifier = Modifier.padding(start = 52.dp))
                    }
                }

                item {
                    Spacer(Modifier.height(32.dp))
                }
            }
        }
    }

    // Bottom Sheet for Settings
    if (selectedSlotDetail != null && selectedSlotRoomId != null && userProfile != null) {
        ModalBottomSheet(
            onDismissRequest = {
                selectedSlotDetail = null
                selectedSlotRoomId = null
            },
            sheetState = sheetState
        ) {
            SlotSettingsSheet(
                slot = selectedSlotDetail!!,
                profile = userProfile!!,
                onUpdate = { key, value ->
                    userViewModel.updateSlotPreferences(selectedSlotRoomId!!, selectedSlotDetail!!.slot_id, key, value)
                    // Optimistically update local state to reflect change immediately in UI
                    // (Real app would rely on flow update, but this makes UI snappy)
                }
            )
        }
    }
}

@Composable
fun SlotOverrideItem(
    slot: TrackedSlotDetail,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(start = 52.dp, end = 16.dp, top = 16.dp, bottom = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = if (slot.player_alias.isNullOrBlank()) slot.player_name else "${slot.player_alias} (${slot.player_name})",
                style = MaterialTheme.typography.bodyLarge
            )
        }
        Icon(
            imageVector = Icons.Default.Settings,
            contentDescription = "Edit Settings",
            tint = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
fun SlotSettingsSheet(
    slot: TrackedSlotDetail,
    profile: UserProfile,
    onUpdate: (String, Boolean?) -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .padding(bottom = 32.dp) // extra padding for nav bar
            .navigationBarsPadding()
    ) {
        Text(
            text = "Override Settings",
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(bottom = 16.dp)
        )
        Text(
            text = "Settings for ${slot.player_alias ?: slot.player_name}",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(bottom = 24.dp)
        )

        LazyColumn(modifier = Modifier.weight(1f, fill = false)) {

            // 1. EVENTS SECTION
            item { SectionHeader("Events") }
            item {
                OverrideToggle(
                    title = "Progression items",
                    currentValue = slot.notify_progression,
                    defaultValue = profile.notify_progression_default,
                    onValueChange = { onUpdate("notify_progression", it) }
                )
                Spacer(Modifier.height(16.dp))

                OverrideToggle(
                    title = "Useful items",
                    currentValue = slot.notify_useful,
                    defaultValue = profile.notify_useful_default,
                    onValueChange = { onUpdate("notify_useful", it) }
                )
                Spacer(Modifier.height(16.dp))

                OverrideToggle(
                    title = "Hints (World)",
                    currentValue = slot.notify_hints,
                    defaultValue = profile.notify_hints_default,
                    onValueChange = { onUpdate("notify_hints", it) }
                )
                Spacer(Modifier.height(16.dp))

                OverrideToggle(
                    title = "Hints (Remote)",
                    currentValue = slot.notify_hints_remote_items,
                    defaultValue = profile.notify_hints_remote_items_default,
                    onValueChange = { onUpdate("notify_hints_remote_items", it) }
                )
                Spacer(Modifier.height(16.dp))

                OverrideToggle(
                    title = "Finished slots",
                    currentValue = slot.notify_finished,
                    defaultValue = profile.notify_finished_default,
                    onValueChange = { onUpdate("notify_finished", it) }
                )
            }

            // 2. BEHAVIOR SECTION
            item { SectionHeader("Behavior") }
            item {
                // NEW TOGGLE
                OverrideToggle(
                    title = "Suppress locally found items",
                    currentValue = slot.suppress_self_found,
                    defaultValue = profile.suppress_self_found_default,
                    onValueChange = { onUpdate("suppress_self_found", it) }
                )
                Spacer(Modifier.height(16.dp))

                OverrideToggle(
                    title = "Suppress items from my other slots",
                    currentValue = slot.suppress_own_events,
                    defaultValue = profile.suppress_own_events_default,
                    onValueChange = { onUpdate("suppress_own_events", it) }
                )
            }

            // 3. FORMAT SECTION
            item { SectionHeader("Format") }
            item {
                OverrideToggle(
                    title = "Combine notifications",
                    currentValue = slot.combine_notifications,
                    defaultValue = profile.combine_notifications_default,
                    onValueChange = { onUpdate("combine_notifications", it) }
                )
                Spacer(Modifier.height(16.dp))

                OverrideToggle(
                    title = "Remove emojis",
                    currentValue = slot.remove_emojis,
                    defaultValue = profile.remove_emojis_default,
                    onValueChange = { onUpdate("remove_emojis", it) }
                )
                Spacer(Modifier.height(16.dp))

                OverrideToggle(
                    title = "Shorter notifications",
                    currentValue = slot.use_condensed_messages,
                    defaultValue = profile.use_condensed_messages_default,
                    onValueChange = { onUpdate("use_condensed_messages", it) }
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OverrideToggle(
    title: String,
    currentValue: Boolean?, // null = use default
    defaultValue: Boolean,
    onValueChange: (Boolean?) -> Unit
) {
    val isOverridden = currentValue != null
    val effectiveValue = currentValue ?: defaultValue

    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(text = title, style = MaterialTheme.typography.bodyLarge)
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

        // Simple 2-state toggle used to set the Override (True or False)
        // If currently NULL (Default), we still show the toggle in the position of the Default value,
        // but selecting it will explicitly set the override.
        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
            val options = listOf("Off", "On")
            val selectedIndex = if (effectiveValue) 1 else 0

            options.forEachIndexed { index, label ->
                SegmentedButton(
                    selected = index == selectedIndex,
                    onClick = {
                        val newValue = (index == 1) // 0 -> false, 1 -> true
                        // If we are already in this state via Default, clicking it forces an Override of that state
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