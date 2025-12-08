package com.jones.aptracker.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onBackClick: () -> Unit,
    onNavigateToSlotOverrides: () -> Unit, // <--- This was missing in your definition
    userViewModel: UserViewModel = viewModel()
) {
    val userProfile by userViewModel.userProfile.collectAsState()
    val errorMessage by userViewModel.errorMessage.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

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
                title = { Text("Notification Settings") },
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
                    text = "Global Defaults",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(vertical = 16.dp),
                    color = MaterialTheme.colorScheme.primary
                )
            }

            // --- PER-SLOT OVERRIDES BUTTON ---
            item {
                ProfileMenuItem(
                    icon = Icons.Default.Tune,
                    title = "Per-Slot Overrides",
                    subtitle = "Customize specific rooms or players",
                    onClick = onNavigateToSlotOverrides
                )
                HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))
            }

            // --- GLOBAL TOGGLES ---
            item {
                userProfile?.let { profile ->
                    Column {
                        NotificationToggle(
                            text = "Shorter notifications",
                            description = "Show shorter notification messages.",
                            checked = profile.use_condensed_messages_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(useCondensed = it) }
                        )
                        HorizontalDivider()
                        NotificationToggle(
                            text = "Progression items",
                            description = "Notify when a progression item is received.",
                            checked = profile.notify_progression_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(progression = it) }
                        )
                        HorizontalDivider()
                        NotificationToggle(
                            text = "Useful items",
                            description = "Notify when a useful item is received.",
                            checked = profile.notify_useful_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(useful = it) }
                        )
                        HorizontalDivider()
                        NotificationToggle(
                            text = "Hints in my world",
                            description = "Notify when someone hints for an item at one of your locations.",
                            checked = profile.notify_hints_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(hints = it) }
                        )
                        HorizontalDivider()
                        NotificationToggle(
                            text = "Hints for my items",
                            description = "Notify when a hint reveals your item's location remotely.",
                            checked = profile.notify_hints_remote_items_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(remoteHints = it) }
                        )
                        HorizontalDivider()
                        NotificationToggle(
                            text = "Finished slots",
                            description = "Notify for events after a slot has goaled.",
                            checked = profile.notify_finished_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(finished = it) }
                        )
                    }
                } ?: Box(modifier = Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
            }
        }
    }
}

@Composable
fun NotificationToggle(
    text: String,
    description: String? = null,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text, style = MaterialTheme.typography.bodyLarge)
            if (description != null) {
                Text(
                    text = description,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange,
            modifier = Modifier.padding(start = 16.dp)
        )
    }
}

