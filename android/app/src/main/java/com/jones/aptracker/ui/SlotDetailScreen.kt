package com.jones.aptracker.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jones.aptracker.network.TrackedSlotDetail
import com.jones.aptracker.network.RoomWithTrackedSlots
import com.jones.aptracker.network.SlotItemThreshold

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SlotDetailScreen(
    roomDbId: Int,
    slotId: Int,
    onBackClick: () -> Unit,
    onNavigateToHistory: (Int, String, String?) -> Unit,
    userViewModel: UserViewModel = viewModel()
) {
    val trackedSlotsByRoom by userViewModel.trackedSlotsByRoom.collectAsState()
    val userProfile by userViewModel.userProfile.collectAsState()

    // Find the room and slot from the current data
    val room = remember(trackedSlotsByRoom, roomDbId) {
        trackedSlotsByRoom.find { it.room_db_id == roomDbId }
    }
    val slot = remember(room, slotId) {
        room?.tracked_slots?.find { it.slot_id == slotId }
    }

    var showSettingsSheet by remember { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var showConsole by remember { mutableStateOf(false) }

    LaunchedEffect(roomDbId, slotId) {
        userViewModel.fetchSlotThresholds(roomDbId, slotId)
        userViewModel.fetchAvailableItems(roomDbId, slotId)
    }
    val thresholds by userViewModel.slotThresholds.collectAsState()
    val availableItems by userViewModel.availableItems.collectAsState()

    val isDark = isSystemInDarkTheme()
    val finishedColor = if (isDark) Color(0xFF81C784) else Color(0xFF0E8A0E)

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Slot Details") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        if (slot == null || room == null) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                contentAlignment = Alignment.Center
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator()
                    Spacer(Modifier.height(16.dp))
                    Text(
                        text = "Loading slot data...",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        } else {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp)
            ) {
                // =============================================
                // HEADER SECTION
                // =============================================
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    )
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(20.dp)
                    ) {
                        // Player Name (Title)
                        val displayName = if (slot.player_alias.isNullOrBlank()) {
                            slot.player_name
                        } else {
                            slot.player_alias
                        }

                        Row(verticalAlignment = Alignment.CenterVertically) {
                            if (slot.is_finished) {
                                Text("🏁 ", style = MaterialTheme.typography.headlineSmall)
                            }
                            Text(
                                text = displayName,
                                style = MaterialTheme.typography.headlineSmall,
                                fontWeight = FontWeight.Bold,
                                color = if (slot.is_finished) finishedColor else MaterialTheme.colorScheme.onSurface
                            )
                        }

                        // Original slot name (if alias differs)
                        if (!slot.player_alias.isNullOrBlank()) {
                            Text(
                                text = slot.player_name,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }

                        Spacer(Modifier.height(12.dp))

                        // Metadata Grid
                        Row(modifier = Modifier.fillMaxWidth()) {
                            Column(modifier = Modifier.weight(1f)) {
                                MetadataItem(label = "GAME", value = slot.game ?: "Unknown")
                                Spacer(Modifier.height(8.dp))
                                MetadataItem(
                                    label = "STATUS",
                                    value = if (slot.is_finished) "Completed" else "In Progress"
                                )
                            }
                            Column(modifier = Modifier.weight(1f)) {
                                MetadataItem(label = "ROOM", value = room.room_alias)
                                Spacer(Modifier.height(8.dp))
                                MetadataItem(
                                    label = "LAST ACTIVITY",
                                    value = if (slot.last_activity != null) {
                                        formatRelativeTime(slot.last_activity)
                                    } else {
                                        "No activity yet"
                                    }
                                )
                            }
                        }

                        if (room.host != null) {
                            Spacer(Modifier.height(8.dp))
                            MetadataItem(label = "HOST", value = room.host)
                        }
                    }
                }

                Spacer(Modifier.height(20.dp))

                // =============================================
                // QUICK ACTIONS
                // =============================================
                Text(
                    text = "Quick Actions",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(bottom = 8.dp)
                )

                // View History
                ActionCard(
                    icon = Icons.Default.History,
                    title = "View History",
                    subtitle = "See all items received by this slot",
                    onClick = { onNavigateToHistory(roomDbId, room.room_alias, slot.player_name) }
                )

                Spacer(Modifier.height(8.dp))

                // Notification Settings
                ActionCard(
                    icon = Icons.Default.Notifications,
                    title = "Notification Settings",
                    subtitle = "Customize how you are notified for this slot",
                    onClick = { showSettingsSheet = true }
                )

                Spacer(Modifier.height(16.dp))

                // Notification Thresholds
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
                    ),
                    shape = RoundedCornerShape(16.dp)
                ) {
                    ThresholdSection(
                        roomDbId = roomDbId,
                        slotId = slotId,
                        thresholds = thresholds,
                        availableItems = availableItems,
                        onSave = { name, count ->
                            userViewModel.saveSlotThreshold(roomDbId, slotId, name, count)
                        },
                        onDelete = { thresholdId ->
                            userViewModel.deleteSlotThreshold(roomDbId, slotId, thresholdId)
                        }
                    )
                }

                Spacer(Modifier.height(16.dp))

                // WebSocket Console Section=============================================
                // WEBSOCKET CONSOLE (PLACEHOLDER)
                // =============================================
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
                ) {
                    Column(modifier = Modifier.fillMaxWidth()) {
                        // Console Header (clickable to expand)
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { showConsole = !showConsole }
                                .padding(16.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(
                                imageVector = Icons.Default.Terminal,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(24.dp)
                            )
                            Spacer(Modifier.width(12.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = "Text Client",
                                    style = MaterialTheme.typography.titleMedium,
                                    fontWeight = FontWeight.SemiBold
                                )
                            }

                            // Coming Soon badge
                            Surface(
                                color = MaterialTheme.colorScheme.tertiary.copy(alpha = 0.15f),
                                shape = RoundedCornerShape(8.dp)
                            ) {
                                Text(
                                    text = "Coming Soon",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.tertiary,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                                )
                            }

                            Spacer(Modifier.width(8.dp))
                            Icon(
                                imageVector = if (showConsole) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                                contentDescription = if (showConsole) "Collapse" else "Expand",
                                tint = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }

                        // Console Body (expandable)
                        if (showConsole) {
                            HorizontalDivider()
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(16.dp)
                            ) {
                                // Placeholder message log
                                Box(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .height(160.dp)
                                        .background(
                                            MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                                            RoundedCornerShape(8.dp)
                                        )
                                        .border(
                                            1.dp,
                                            MaterialTheme.colorScheme.outlineVariant,
                                            RoundedCornerShape(8.dp)
                                        ),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Text(
                                        text = "Connect to this slot's Archipelago server to send text commands and view real-time messages using a built-in text client.\n\nThis feature is under development.",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                                        textAlign = TextAlign.Center,
                                        modifier = Modifier.padding(24.dp)
                                    )
                                }

                                Spacer(Modifier.height(8.dp))

                                // Disabled text input
                                TextField(
                                    value = "",
                                    onValueChange = {},
                                    enabled = false,
                                    placeholder = { Text("Send a command...") },
                                    modifier = Modifier.fillMaxWidth(),
                                    singleLine = true
                                )
                            }
                        }
                    }
                }

                Spacer(Modifier.height(32.dp))
            }
        }
    }

    // --- Notification Settings Bottom Sheet ---
    if (showSettingsSheet && slot != null && userProfile != null) {
        ModalBottomSheet(
            onDismissRequest = { showSettingsSheet = false },
            sheetState = sheetState
        ) {
            SlotSettingsSheet(
                slot = slot,
                profile = userProfile!!,
                onUpdate = { key, value ->
                    userViewModel.updateSlotPreferences(roomDbId, slotId, key, value)
                },
                onApplyToAll = {
                    userViewModel.applySlotSettingsToAll(roomDbId, slotId)
                    showSettingsSheet = false
                }
            )
        }
    }
}

@Composable
fun MetadataItem(label: String, value: String) {
    Column {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface
        )
    }
}

@Composable
fun ActionCard(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    subtitle: String,
    onClick: () -> Unit
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(24.dp)
            )
            Spacer(Modifier.width(16.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Medium
                )
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Icon(
                imageVector = Icons.Default.ChevronRight,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
            )
        }
    }
}

@Composable
fun ThresholdSection(
    roomDbId: Int,
    slotId: Int,
    thresholds: List<SlotItemThreshold>,
    availableItems: List<String>,
    onSave: (String, Int) -> Unit,
    onDelete: (Int) -> Unit
) {
    var showAddDialog by remember { mutableStateOf(false) }

    Column(modifier = Modifier.padding(16.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "Item Notification Thresholds",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold
            )
            TextButton(onClick = { showAddDialog = true }) {
                Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(4.dp))
                Text("Add")
            }
        }

        if (thresholds.isEmpty()) {
            Text(
                text = "No thresholds set. Add one to only be notified after receiving a certain count of an item (e.g. 70 Yoshi Eggs).",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                modifier = Modifier.padding(vertical = 8.dp)
            )
        } else {
            thresholds.forEach { threshold ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(
                        Icons.Default.NotificationsActive,
                        contentDescription = null,
                        modifier = Modifier.size(20.dp),
                        tint = MaterialTheme.colorScheme.primary
                    )
                    Spacer(Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(text = threshold.item_name, style = MaterialTheme.typography.bodyLarge)
                        Text(
                            text = "Notify at ${threshold.threshold} received",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    IconButton(onClick = { onDelete(threshold.id) }) {
                        Icon(
                            Icons.Default.Delete,
                            contentDescription = "Delete",
                            modifier = Modifier.size(20.dp),
                            tint = MaterialTheme.colorScheme.error.copy(alpha = 0.7f)
                        )
                    }
                }
            }
        }
    }

    if (showAddDialog) {
        AddThresholdDialog(
            availableItems = availableItems,
            onDismiss = { showAddDialog = false },
            onSave = { name, count ->
                onSave(name, count)
                showAddDialog = false
            }
        )
    }
}

@Composable
fun AddThresholdDialog(
    availableItems: List<String>,
    onDismiss: () -> Unit,
    onSave: (String, Int) -> Unit
) {
    var itemName by remember { mutableStateOf("") }
    var thresholdStr by remember { mutableStateOf("") }
    var expanded by remember { mutableStateOf(false) }

    val filteredItems = remember(itemName, availableItems) {
        if (itemName.isEmpty()) {
            availableItems.take(50)
        } else {
            availableItems.filter { it.contains(itemName, ignoreCase = true) }.take(50)
        }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add Item Threshold") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Text(
                    "Search for an item and enter the count at which you want to be notified.",
                    style = MaterialTheme.typography.bodySmall
                )
                
                Box {
                    Column {
                        OutlinedTextField(
                            value = itemName,
                            onValueChange = { 
                                itemName = it
                                expanded = true
                            },
                            label = { Text("Item Name") },
                            placeholder = { Text("Search items...") },
                            modifier = Modifier.fillMaxWidth(),
                            trailingIcon = {
                                IconButton(onClick = { expanded = !expanded }) {
                                    Icon(
                                        if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                                        contentDescription = null
                                    )
                                }
                            }
                        )
                        
                        if (expanded && filteredItems.isNotEmpty()) {
                            Card(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(top = 4.dp)
                                    .heightIn(max = 200.dp),
                                elevation = CardDefaults.cardElevation(defaultElevation = 8.dp),
                                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                            ) {
                                LazyColumn {
                                    items(filteredItems) { item ->
                                        Box(
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .clickable {
                                                    itemName = item
                                                    expanded = false
                                                }
                                                .padding(16.dp)
                                        ) {
                                            Text(item)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                OutlinedTextField(
                    value = thresholdStr,
                    onValueChange = { if (it.all { char -> char.isDigit() }) thresholdStr = it },
                    label = { Text("Notify at count") },
                    placeholder = { Text("e.g. 70") },
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
                )
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    val count = thresholdStr.toIntOrNull() ?: 0
                    if (itemName.isNotBlank() && count > 0) {
                        onSave(itemName, count)
                    }
                },
                enabled = itemName.isNotBlank() && thresholdStr.isNotBlank()
            ) {
                Text("Save")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel")
            }
        }
    )
}
