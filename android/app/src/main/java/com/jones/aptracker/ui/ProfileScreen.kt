package com.jones.aptracker.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.NotificationsPaused
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import kotlinx.coroutines.delay
import java.time.Instant

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(
    userViewModel: UserViewModel = viewModel(),
    onLogoutClick: () -> Unit,
    onGuestUpgradeClick: () -> Unit,
    onIgnoreListClick: () -> Unit,
    onWhitelistClick: () -> Unit,
    onCreditsClick: () -> Unit,
    onNavigateToSettings: () -> Unit,
    onNavigateToGuide: () -> Unit = {},
    onShowWhatsNew: () -> Unit = {},
    onNavigateToArchived: () -> Unit
) {


    val userProfile by userViewModel.userProfile.collectAsState()
    val isAutoSyncEnabled by userViewModel.isAutoSyncEnabled.collectAsState()

    val dateFormatPresetKey by userViewModel.dateFormatPreset.collectAsState()
    val dateFormatPreset = remember(dateFormatPresetKey) { DateFormatPreset.fromKey(dateFormatPresetKey) }

    // State for Delete Dialog
    var showDeleteDialog by remember { mutableStateOf(false) }
    var showClearHistoryDialog by remember { mutableStateOf(false) }

    var showSnoozeDialog by remember { mutableStateOf(false) }
    var now by remember { mutableStateOf(Instant.now()) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(60_000L)
            now = Instant.now()
        }
    }

    val context = androidx.compose.ui.platform.LocalContext.current
    val integrationMessage by userViewModel.integrationMessage.collectAsState()
    val errorMessage by userViewModel.errorMessage.collectAsState()

    LaunchedEffect(integrationMessage) {
        integrationMessage?.let {
            android.widget.Toast.makeText(context, it, android.widget.Toast.LENGTH_SHORT).show()
            userViewModel.clearIntegrationMessage()
        }
    }

    LaunchedEffect(errorMessage) {
        errorMessage?.let {
            android.widget.Toast.makeText(context, it, android.widget.Toast.LENGTH_LONG).show()
            userViewModel.clearErrorMessage()
        }
    }

    val globalSnoozeRaw = userProfile?.global_snooze_until
    val isGlobalSnoozeActive = remember(globalSnoozeRaw, now) {
        if (globalSnoozeRaw == null) false else {
            try {
                Instant.parse(globalSnoozeRaw).isAfter(now)
            } catch (e: Exception) { false }
        }
    }

    if (showSnoozeDialog) {
        SnoozeDialog(
            title = "Global Snooze",
            currentSnoozeUntil = if (isGlobalSnoozeActive) globalSnoozeRaw else null,
            activeSnoozeDetails = emptyList(),
            dateFormatPreset = dateFormatPreset,
            onDismiss = { showSnoozeDialog = false },
            onSnoozeSelected = { minutes ->
                userViewModel.setGlobalSnooze(minutes)
                showSnoozeDialog = false
            }
        )
    }

    Scaffold(
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = padding.calculateTopPadding())
                .verticalScroll(rememberScrollState())
                .padding(
                    start = 16.dp,
                    end = 16.dp,
                    top = 16.dp,
                    bottom = padding.calculateBottomPadding() + 16.dp
                ),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {

            // --- Header: User Info ---
            userProfile?.let { profile ->
                if (profile.avatar_url != null) {
                    AsyncImage(
                        model = profile.avatar_url,
                        contentDescription = "Avatar",
                        modifier = Modifier
                            .size(100.dp)
                            .clip(CircleShape)
                            .border(2.dp, MaterialTheme.colorScheme.primary, CircleShape),
                        contentScale = ContentScale.Crop
                    )
                } else {
                    Icon(
                        Icons.Default.AccountCircle,
                        null,
                        modifier = Modifier.size(100.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }

                Spacer(Modifier.height(16.dp))

                Text(
                    text = profile.discord_username ?: "Guest",
                    style = MaterialTheme.typography.headlineMedium
                )

                if (profile.is_guest) {
                    Button(onClick = onGuestUpgradeClick, modifier = Modifier.padding(top = 8.dp)) {
                        Text("Link Discord Account")
                    }
                }
            }

            Spacer(Modifier.height(32.dp))

            val snoozeSubtitle = userProfile?.global_snooze_until?.let { snoozeTime ->
                "Active until ${formatIsoDate(snoozeTime, dateFormatPreset)}"
            } ?: "Silence all notifications temporarily"

            // --- Menu Options ---

            ProfileMenuItem(
                icon = Icons.Default.Info,
                title = "Guide & FAQ",
                subtitle = "Learn room tracking, mutes, whitelists, and milestones",
                onClick = onNavigateToGuide
            )

            ProfileMenuItem(
                icon = Icons.Default.Info,
                title = "What's New in v${com.jones.aptracker.BuildConfig.VERSION_NAME}",
                subtitle = "View recent patch highlights and feature updates",
                onClick = onShowWhatsNew
            )

            ProfileMenuItem(
                icon = Icons.Default.Settings,
                title = "Notification Settings",
                subtitle = "Global defaults for new rooms",
                onClick = onNavigateToSettings
            )

            ProfileMenuItem(
                icon = Icons.Default.NotificationsPaused,
                title = "Snooze All Notifications",
                subtitle = if (isGlobalSnoozeActive) {
                    "Active until ${formatIsoDate(globalSnoozeRaw!!, dateFormatPreset)}"
                } else {
                    null
                },
                onClick = { showSnoozeDialog = true }
            )

            ProfileMenuItem(
                icon = Icons.Default.Inventory2,
                title = "Archived Rooms",
                subtitle = "View finished or inactive games",
                onClick = onNavigateToArchived
            )


            ProfileMenuItem(
                icon = Icons.Default.VisibilityOff,
                title = "Ignore List",
                subtitle = "Mute notifications for specific items",
                onClick = onIgnoreListClick
            )

            ProfileMenuItem(
                icon = Icons.Default.Visibility,
                title = "Whitelist",
                subtitle = "Always deliver notifications for specific items",
                onClick = onWhitelistClick
            )

            HorizontalDivider(Modifier.padding(vertical = 16.dp))

            // --- Integrations ---
            Text(
                "Integrations",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp)
            )

            CheeseIntegrationCard(
                isConnected = userProfile?.is_cheese_connected ?: false,
                isAutoSyncEnabled = isAutoSyncEnabled,
                defaultPing = userProfile?.cheese_default_ping,
                onAutoSyncChanged = { userViewModel.setAutoSync(it) },
                onConnect = { key -> userViewModel.connectCheeseTracker(key) },
                onSync = { userViewModel.manualSyncCheese() },
                onDisconnect = { userViewModel.disconnectCheese() },
                onDefaultPingChange = { userViewModel.updateCheeseDefaultPing(it) }
            )

            HorizontalDivider(Modifier.padding(vertical = 16.dp))

            // --- App Info ---
            ProfileMenuItem(
                icon = Icons.Default.Info,
                title = "About & Credits",
                onClick = onCreditsClick
            )

            HorizontalDivider(Modifier.padding(vertical = 16.dp))

            // --- Logout ---
            OutlinedButton(
                onClick = onLogoutClick,
                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.secondary),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Log Out")
            }

            Spacer(Modifier.height(24.dp))

            // --- 2. DELETE ACCOUNT ---
            OutlinedButton(
                onClick = { showDeleteDialog = true },
                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Delete Account",
                    fontWeight = FontWeight.Bold)
            }
            Spacer(Modifier.height(48.dp))

            // --- DEBUG SECTION ---
            HorizontalDivider()
            Spacer(Modifier.height(16.dp))

            Text(
                "Debug Options",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(Modifier.height(8.dp))

            OutlinedButton(
                onClick = { showClearHistoryDialog = true },
                modifier = Modifier.fillMaxWidth()
            ) {
                Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Text("Clear Local History")
            }

            Text(
                "Deletes all locally cached items and hints, forcing a fresh download from the server on next view.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 8.dp, bottom = 24.dp)
            )

            OutlinedButton(
                onClick = { userViewModel.sendTestNotification() },
                modifier = Modifier.fillMaxWidth()
            ) {
                Icon(Icons.Default.NotificationsPaused, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Text("Trigger Test Notification")
            }

            Text(
                "Sends a push notification to this device immediately to test layout and actions.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 8.dp, bottom = 24.dp)
            )
        }
    }

    if (showClearHistoryDialog) {
        AlertDialog(
            onDismissRequest = { showClearHistoryDialog = false },
            title = { Text("Clear Local History?") },
            text = { Text("This will delete all locally cached items and hints. They will be re-downloaded from the server next time you view the history screen.") },
            confirmButton = {
                Button(onClick = {
                    showClearHistoryDialog = false
                    userViewModel.clearLocalHistory()
                }) {
                    Text("Clear")
                }
            },
            dismissButton = {
                TextButton(onClick = { showClearHistoryDialog = false }) {
                    Text("Cancel")
                }
            }
        )
    }

    // --- Delete Confirmation Dialog ---
    if (showDeleteDialog) {
        AlertDialog(
            onDismissRequest = { showDeleteDialog = false },
            title = { Text("Delete Your Account?") },
            text = {
                Text(
                    "This action is permanent and cannot be undone. " +
                            "All of your tracked rooms, slots, and notification settings will be immediately deleted."
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        showDeleteDialog = false
                        userViewModel.deleteAccount(onAccountDeleted = onLogoutClick)
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
                ) {
                    Text("DELETE PERMANENTLY")
                }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteDialog = false }) {
                    Text("Cancel")
                }
            }
        )
    }
}

@Composable
fun ProfileMenuItem(
    icon: ImageVector,
    title: String,
    subtitle: String? = null,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
        Spacer(Modifier.width(16.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            if (subtitle != null) {
                Text(
                    subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        Icon(Icons.Default.KeyboardArrowRight, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun CheeseDefaultPingSelector(
    defaultPing: String?,
    onDefaultPingChange: (String?) -> Unit
) {
    var expanded by remember { mutableStateOf(false) }
    val currentLabel = CHEESE_PING_OPTIONS.find { it.id == defaultPing }?.label ?: "Not set"

    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            "Default ping for new claims",
            style = MaterialTheme.typography.bodyLarge
        )
        Text(
            "Applied when you claim a new slot. Existing claims are left as-is.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.height(8.dp))
        Box {
            OutlinedButton(
                onClick = { expanded = true },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(currentLabel, modifier = Modifier.weight(1f))
                Icon(Icons.Default.KeyboardArrowRight, contentDescription = null)
            }
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                DropdownMenuItem(
                    text = { Text("Not set") },
                    onClick = {
                        expanded = false
                        onDefaultPingChange(null)
                    }
                )
                CHEESE_PING_OPTIONS.forEach { option ->
                    DropdownMenuItem(
                        text = { Text(option.label) },
                        onClick = {
                            expanded = false
                            onDefaultPingChange(option.id)
                        }
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CheeseIntegrationCard(
    isConnected: Boolean,
    isAutoSyncEnabled: Boolean,
    defaultPing: String?,
    onAutoSyncChanged: (Boolean) -> Unit,
    onConnect: (String) -> Unit,
    onSync: () -> Unit,
    onDisconnect: () -> Unit,
    onDefaultPingChange: (String?) -> Unit
) {
    var apiKey by remember { mutableStateOf("") }
    var guestDiscordName by remember { mutableStateOf("") }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
        ) {
            // Header
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(
                    text = "Cheese Tracker",
                    style = MaterialTheme.typography.titleMedium
                )
            }

            Spacer(modifier = Modifier.height(8.dp))

            if (isConnected) {
                // CONNECTED STATE
                Text(
                    text = "You are connected to your Cheese Tracker!",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.height(16.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            imageVector = Icons.Default.CheckCircle,
                            contentDescription = "Connected",
                            tint = MaterialTheme.colorScheme.primary
                        )
                        Spacer(Modifier.width(8.dp))
                        Text(
                            "Connected",
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }

                    TextButton(
                        onClick = onDisconnect,
                        colors = ButtonDefaults.textButtonColors(
                            contentColor = MaterialTheme.colorScheme.error
                        )
                    ) {
                        Text("Disconnect")
                    }
                }

                Spacer(modifier = Modifier.height(8.dp))
                HorizontalDivider()
                Spacer(modifier = Modifier.height(8.dp))

                // Auto-sync Toggle
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onAutoSyncChanged(!isAutoSyncEnabled) }
                        .padding(vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            "Auto-sync",
                            style = MaterialTheme.typography.bodyLarge
                        )
                        Text(
                            "Sync when opening the app",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    Switch(
                        checked = isAutoSyncEnabled,
                        onCheckedChange = onAutoSyncChanged,
                        modifier = Modifier.padding(start = 16.dp)
                    )
                }

                Spacer(Modifier.height(8.dp))
                HorizontalDivider()
                Spacer(Modifier.height(8.dp))

                // Default ping preference (applied to newly claimed slots only)
                CheeseDefaultPingSelector(
                    defaultPing = defaultPing,
                    onDefaultPingChange = onDefaultPingChange
                )

                Spacer(Modifier.height(8.dp))

                Button(
                    onClick = { onSync() },
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.outlinedButtonColors()
                ) {
                    Icon(Icons.Default.Refresh, contentDescription = "Sync")
                    Spacer(Modifier.width(8.dp))
                    Text("Sync Now")
                }

            } else {
                // DISCONNECTED STATE
                Text(
                    text = "Sync your rooms and tracked slots with Cheesetracker.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.height(16.dp))

                OutlinedTextField(
                    value = apiKey,
                    onValueChange = { apiKey = it },
                    label = { Text("API Key") },
                    placeholder = { Text("Paste key from Cheese Tracker") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )

                Spacer(modifier = Modifier.height(16.dp))

                Row(
                    horizontalArrangement = Arrangement.End,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Button(
                        onClick = { onConnect(apiKey) },
                        enabled = apiKey.isNotBlank()
                    ) {
                        Text("Connect & Sync")
                    }
                }
            }
        }
    }
}