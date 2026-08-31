package com.jones.aptracker.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Tune

import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jones.aptracker.data.FinishedDefinition
import com.jones.aptracker.diagnostics.CrashReporter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onBackClick: () -> Unit,
    onNavigateToSlotOverrides: () -> Unit,
    onNavigateToGuide: () -> Unit = {},
    onShowWhatsNew: () -> Unit = {},
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
                title = { Text("Settings & Preferences") },
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

            // --- TOP SECTION: OVERRIDES ---
            item {
                Text(
                    text = "Global Defaults",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(vertical = 16.dp),
                    color = MaterialTheme.colorScheme.primary
                )
            }

            item {
                ProfileMenuItem(
                    icon = Icons.Default.Tune,
                    title = "Per-Slot Overrides",
                    subtitle = "Customize specific rooms or players",
                    onClick = onNavigateToSlotOverrides
                )
                HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))
            }


            // --- MAIN TOGGLES ---
            item {
                userProfile?.let { profile ->
                    Column {
                        // 1. EVENTS SECTION
                        SectionHeader("Events")

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
                            text = "Filler items",
                            description = "Notify when a filler item is received.",
                            checked = profile.notify_filler_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(filler = it) }
                        )
                        HorizontalDivider()

                        NotificationToggle(
                            text = "Trap items",
                            description = "Notify when a trap item is received.",
                            checked = profile.notify_trap_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(trap = it) }
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
                            text = "Keep notifying finished slots",
                            description = "Items and hints for a slot that has already finished. " +
                                "You always get the finish notification itself.",
                            checked = profile.notify_finished_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(finished = it) }
                        )
                        HorizontalDivider()

                        // Sits directly under the finished-slot toggle because it defines
                        // what that toggle -- and every "show finished" filter -- acts on.
                        val currentDefinition = remember(profile.finished_definition_default) {
                            FinishedDefinition.fromWire(profile.finished_definition_default)
                        }

                        SettingsDropdownRow(
                            title = "Finished means",
                            description = currentDefinition.description,
                            selected = currentDefinition,
                            options = FinishedDefinition.entries,
                            optionLabel = { it.label },
                            onSelect = { userViewModel.setFinishedDefinition(it) }
                        )

                        // 2. BEHAVIOR SECTION
                        SectionHeader("Behavior")

                        NotificationToggle(
                            text = "Suppress if I'm connected",
                            description = "Don't notify me for slots I'm currently playing.",
                            checked = profile.suppress_connected_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(suppressConnected = it) }
                        )
                        HorizontalDivider()

                        NotificationToggle(
                            text = "Suppress locally found items",
                            description = "Don't notify for items found in the same slot that I'm playing.",
                            checked = profile.suppress_self_found_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(suppressSelfFound = it) }
                        )
                        HorizontalDivider()

                        NotificationToggle(
                            text = "Suppress items from my other slots",
                            description = "Don't notify me if an item is found in one of my other tracked slots.",
                            checked = profile.suppress_own_events_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(suppressOwn = it) }
                        )

                        // 3. FORMAT SECTION
                        SectionHeader("Format")

                        NotificationToggle(
                            text = "Combine notifications",
                            description = "Group multiple notifications into a single summary.",
                            checked = profile.combine_notifications_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(combine = it) }
                        )
                        HorizontalDivider()

                        NotificationToggle(
                            text = "Remove emojis",
                            description = "Strip icons (🏆, ✅) from notification titles.",
                            checked = profile.remove_emojis_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(removeEmojis = it) }
                        )
                        HorizontalDivider()

                        NotificationToggle(
                            text = "Shorter notifications",
                            description = "Show shorter notification messages.",
                            checked = profile.use_condensed_messages_default,
                            onCheckedChange = { userViewModel.updateGlobalPreferences(useCondensed = it) }
                        )
                        HorizontalDivider()

                        // Date Format Setting
                        val dateFormatPresetKey by userViewModel.dateFormatPreset.collectAsState()
                        val currentPreset = remember(dateFormatPresetKey) { DateFormatPreset.fromKey(dateFormatPresetKey) }

                        SettingsDropdownRow(
                            title = "Date format",
                            // The live sample goes on its own line rather than inside the
                            // value. DateFormatPreset.label bakes it in ("Friendly (Jun 8,
                            // 2026 12:05 PM)"), which is far too long for an inline value.
                            description = currentPreset.sample,
                            selected = currentPreset,
                            options = DateFormatPreset.entries,
                            // Name only in the row; the menu keeps the full sample, which is
                            // where seeing the format actually helps you choose.
                            valueLabel = { it.description },
                            optionLabel = { it.label },
                            onSelect = { userViewModel.setDateFormatPreset(it.key) }
                        )
                        HorizontalDivider()

                        // Layout Density Setting
                        val layoutDensityKey by userViewModel.layoutDensity.collectAsState()
                        val currentDensity = remember(layoutDensityKey) {
                            LayoutDensity.fromKey(layoutDensityKey)
                        }

                        SettingsDropdownRow(
                            title = "Layout density",
                            description = currentDensity.summary,
                            selected = currentDensity,
                            options = LayoutDensity.entries,
                            valueLabel = { it.description },
                            optionLabel = { "${it.description} - ${it.summary}" },
                            onSelect = { userViewModel.setLayoutDensity(it.key) }
                        )
                    }

                } ?: Box(modifier = Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
            }

            // Deliberately outside the userProfile block above. This one is stored on the
            // device, not on the account -- Crashlytics reporting is per install -- so it
            // must stay reachable when the profile fetch is still in flight or has failed.
            // Someone turning reporting off is quite likely to be doing it *because* the
            // app is misbehaving.
            item {
                val context = LocalContext.current
                val crashReportingEnabled by CrashReporter.userConsent.collectAsState()

                SectionHeader("Privacy")

                NotificationToggle(
                    text = "Send crash reports",
                    description = "Share crash and performance diagnostics so problems can " +
                        "be found and fixed. No account details or game data are included.",
                    checked = crashReportingEnabled,
                    onCheckedChange = { CrashReporter.setUserConsent(context, it) }
                )
                Text(
                    text = "Applies to this device only. Turning this off also discards " +
                        "any reports waiting to be sent.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(bottom = 24.dp)
                )
            }
        }
    }
}

/**
 * A settings row whose value is chosen from a dropdown.
 *
 * The value gets its own full-width line under the title rather than sitting beside it.
 * Trailing-value layouts work for short values, but these are phrases -- "Goaled or all
 * checks", a formatted date sample -- and squeezing one into the right-hand column
 * crushes the label into a narrow ragged block. Giving it a line costs nothing vertically
 * (the wrapped version was taller anyway) and stops the layout depending on how long the
 * selected option happens to be.
 *
 * The whole row is the touch target, matching the toggle rows above it.
 *
 * [valueLabel] defaults to [optionLabel]; override it when the menu should show more than
 * the row does.
 */
@Composable
fun <T> SettingsDropdownRow(
    title: String,
    description: String?,
    selected: T,
    options: List<T>,
    optionLabel: (T) -> String,
    onSelect: (T) -> Unit,
    valueLabel: (T) -> String = optionLabel
) {
    var expanded by remember { mutableStateOf(false) }

    Box {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { expanded = true }
                .padding(vertical = 12.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.weight(1f)
                )
                Icon(
                    imageVector = Icons.Default.ArrowDropDown,
                    contentDescription = "Change $title",
                    tint = MaterialTheme.colorScheme.primary
                )
            }

            Text(
                text = valueLabel(selected),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.primary
            )

            if (!description.isNullOrBlank()) {
                Text(
                    text = description,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }

        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            options.forEach { option ->
                DropdownMenuItem(
                    text = { Text(optionLabel(option)) },
                    onClick = {
                        onSelect(option)
                        expanded = false
                    },
                    trailingIcon = {
                        if (option == selected) {
                            Icon(Icons.Default.Check, null)
                        }
                    }
                )
            }
        }
    }
}

@Composable
fun SectionHeader(title: String) {
    Text(
        text = title,
        style = MaterialTheme.typography.titleMedium,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(top = 24.dp, bottom = 8.dp)
    )
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
            .toggleable(
                value = checked,
                onValueChange = onCheckedChange,
                role = Role.Switch
            )
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
            onCheckedChange = null,
            modifier = Modifier.padding(start = 16.dp)
        )
    }
}

@Composable
fun SettingsNavigationItem(
    title: String,
    description: String,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text = title, style = MaterialTheme.typography.bodyLarge)
            Text(
                text = description,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        Icon(
            imageVector = Icons.Default.Info,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}