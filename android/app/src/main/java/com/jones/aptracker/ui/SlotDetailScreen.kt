package com.jones.aptracker.ui

import androidx.compose.animation.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import com.jones.aptracker.network.ChatMessage
import com.jones.aptracker.network.ConnectionStatus
import com.jones.aptracker.network.RoomDatapackage
import com.jones.aptracker.network.TrackedSlotDetail
import com.jones.aptracker.network.UserProfile
import com.jones.aptracker.network.SlotItemThreshold
import java.time.Duration
import java.time.Instant
import java.time.format.DateTimeParseException

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SlotDetailScreen(
    roomDbId: Int,
    slotId: Int,
    onBackClick: () -> Unit,
    onNavigateToHistory: (Int, String, String?) -> Unit,
    userViewModel: UserViewModel = viewModel()
) {
    val room by userViewModel.trackedSlotsByRoom.collectAsState()
    val currentRoom = room.find { it.room_db_id == roomDbId }
    val slot = currentRoom?.tracked_slots?.find { it.slot_id == slotId }
    val userProfile by userViewModel.userProfile.collectAsState()

    var showSettingsSheet by remember { mutableStateOf(false) }
    var showAddThresholdDialog by remember { mutableStateOf(false) }
    var isConsoleExpanded by remember { mutableStateOf(false) }

    val textClientViewModel: TextClientViewModel = viewModel()
    val messages by textClientViewModel.messages.collectAsState()
    val connectionStatus by textClientViewModel.connectionStatus.collectAsState()
    val textClientError by textClientViewModel.error.collectAsState()
    val availableLocations by textClientViewModel.availableLocations.collectAsState()
    val availableItems by textClientViewModel.availableItems.collectAsState()
    val datapackage by textClientViewModel.datapackage.collectAsState()

    LaunchedEffect(roomDbId, slotId) {
        userViewModel.fetchSlotThresholds(roomDbId, slotId)
        userViewModel.fetchAvailableItems(roomDbId, slotId)
        textClientViewModel.fetchAutocompleteData(roomDbId, slotId)
    }

    val thresholds by userViewModel.slotThresholds.collectAsState()

    if (slot == null || currentRoom == null) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator()
        }
    } else {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text("Slot Details", style = MaterialTheme.typography.titleMedium) },
                    navigationIcon = {
                        IconButton(onClick = onBackClick) {
                            Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                        }
                    }
                )
            },
            containerColor = Color(0xFF121216) // Darker background as per screenshot
        ) { padding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp)
            ) {
                // 1. MAIN INFO CARD
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = Color(0xFF1E1E24)),
                    shape = RoundedCornerShape(16.dp)
                ) {
                    Column(modifier = Modifier.padding(20.dp)) {
                        Text(
                            text = slot.player_name,
                            style = MaterialTheme.typography.headlineMedium,
                            fontWeight = FontWeight.Bold,
                            color = Color.White
                        )
                        Spacer(Modifier.height(20.dp))
                        
                        // INFO GRID
                        Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                            Row(modifier = Modifier.fillMaxWidth()) {
                                InfoItem(Modifier.weight(1f), "GAME", slot.game ?: "Unknown")
                                InfoItem(Modifier.weight(1f), "ROOM", currentRoom.room_alias)
                            }
                            Row(modifier = Modifier.fillMaxWidth()) {
                                InfoItem(Modifier.weight(1f), "STATUS", if (slot.is_finished) "Finished" else "In Progress")
                                InfoItem(Modifier.weight(1f), "LAST ACTIVITY", formatTimestamp(slot.last_activity))
                            }
                            InfoItem(Modifier.fillMaxWidth(), "HOST", currentRoom.host ?: "archipelago.gg")
                        }
                    }
                }

                Spacer(Modifier.height(24.dp))
                Text("Quick Actions", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = Color.White)
                Spacer(Modifier.height(12.dp))

                // 2. QUICK ACTIONS
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    ActionCard(
                        icon = Icons.Default.History,
                        title = "View History",
                        subtitle = "See all items received by this slot",
                        onClick = { onNavigateToHistory(currentRoom.room_db_id, currentRoom.room_alias, null) }
                    )
                    ActionCard(
                        icon = Icons.Outlined.Notifications,
                        title = "Notification Settings",
                        subtitle = "Customize how you are notified for this slot",
                        onClick = { showSettingsSheet = true }
                    )
                }

                Spacer(Modifier.height(24.dp))

                // 3. THRESHOLDS SECTION
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text("Item Notification Thresholds", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = Color.White)
                    TextButton(onClick = { showAddThresholdDialog = true }) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Add, null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("Add")
                        }
                    }
                }
                
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = Color(0xFF1E1E24)),
                    shape = RoundedCornerShape(16.dp)
                ) {
                    Column(modifier = Modifier.padding(vertical = 8.dp)) {
                        if (thresholds.isEmpty()) {
                            Text(
                                "No thresholds set",
                                modifier = Modifier.padding(16.dp),
                                style = MaterialTheme.typography.bodyMedium,
                                color = Color.Gray
                            )
                        } else {
                            thresholds.forEachIndexed { index, threshold ->
                                ThresholdRow(
                                    threshold = threshold,
                                    onDelete = { userViewModel.deleteSlotThreshold(roomDbId, slotId, threshold.id) }
                                )
                                if (index < thresholds.size - 1) {
                                    HorizontalDivider(
                                        modifier = Modifier.padding(horizontal = 16.dp),
                                        color = Color.DarkGray.copy(alpha = 0.5f)
                                    )
                                }
                            }
                        }
                    }
                }

                Spacer(Modifier.height(24.dp))

                // 4. TEXT CLIENT (CONSOLE)
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = Color(0xFF1E1E24)),
                    shape = RoundedCornerShape(16.dp)
                ) {
                    Column {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { isConsoleExpanded = !isConsoleExpanded }
                                .padding(16.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(Icons.Default.Terminal, null, modifier = Modifier.size(24.dp), tint = Color.White)
                            Spacer(Modifier.width(16.dp))
                            Text("Text Client", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, color = Color.White)
                            Spacer(Modifier.weight(1f))
                            
                            if (connectionStatus == ConnectionStatus.CONNECTED) {
                                Surface(
                                    color = Color(0xFF4CAF50).copy(alpha = 0.1f),
                                    shape = RoundedCornerShape(8.dp)
                                ) {
                                    Text(
                                        "Connected",
                                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                                        style = MaterialTheme.typography.labelSmall,
                                        color = Color(0xFF4CAF50)
                                    )
                                }
                            } else if (connectionStatus == ConnectionStatus.CONNECTING) {
                                CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                            }
                            
                            Spacer(Modifier.width(8.dp))
                            Icon(
                                if (isConsoleExpanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                                null,
                                tint = Color.Gray
                            )
                        }

                        AnimatedVisibility(visible = isConsoleExpanded) {
                            Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                                if (connectionStatus == ConnectionStatus.DISCONNECTED || connectionStatus == ConnectionStatus.ERROR) {
                                    Column(
                                        modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp),
                                        horizontalAlignment = Alignment.CenterHorizontally
                                    ) {
                                        if (textClientError != null) {
                                            Text(textClientError!!, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, textAlign = TextAlign.Center)
                                            Spacer(Modifier.height(12.dp))
                                        }
                                        Button(
                                            onClick = {
                                                val host = currentRoom.host ?: "archipelago.gg"
                                                textClientViewModel.connect(
                                                    host = host,
                                                    slotName = slot.player_name,
                                                    game = slot.game ?: "",
                                                    password = null
                                                )
                                            },
                                            shape = RoundedCornerShape(24.dp)
                                        ) {
                                            Text("Connect Console")
                                        }
                                        TextButton(onClick = { /* Password logic if needed */ }) {
                                            Text("Use Password", style = MaterialTheme.typography.labelSmall, color = Color.Gray)
                                        }
                                    }
                                } else {
                                    // Active Console UI
                                    val listState = rememberLazyListState()
                                    LaunchedEffect(messages.size) {
                                        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.size - 1)
                                    }

                                    Box(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .height(300.dp)
                                            .background(Color(0xFF0A0A0C), RoundedCornerShape(8.dp))
                                            .padding(8.dp)
                                    ) {
                                        LazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
                                            items(messages) { msg ->
                                                ChatMessageRow(msg, datapackage)
                                            }
                                        }
                                    }
                                    
                                    Spacer(Modifier.height(12.dp))
                                    
                                    var inputText by remember { mutableStateOf("") }
                                    OutlinedTextField(
                                        value = inputText,
                                        onValueChange = { inputText = it },
                                        modifier = Modifier.fillMaxWidth(),
                                        placeholder = { Text("Type command...") },
                                        trailingIcon = {
                                            IconButton(onClick = {
                                                if (inputText.isNotBlank()) {
                                                    textClientViewModel.sendMessage(inputText)
                                                    inputText = ""
                                                }
                                            }) { Icon(Icons.Default.Send, null, tint = MaterialTheme.colorScheme.primary) }
                                        },
                                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                                        keyboardActions = KeyboardActions(onSend = {
                                            if (inputText.isNotBlank()) {
                                                textClientViewModel.sendMessage(inputText)
                                                inputText = ""
                                            }
                                        }),
                                        shape = RoundedCornerShape(12.dp),
                                        colors = OutlinedTextFieldDefaults.colors(
                                            unfocusedBorderColor = Color.DarkGray,
                                            focusedTextColor = Color.White,
                                            unfocusedTextColor = Color.White
                                        )
                                    )
                                    Spacer(Modifier.height(8.dp))
                                }
                            }
                        }
                    }
                }
                Spacer(Modifier.height(40.dp))
            }
        }
    }

    // MODALS
    if (showSettingsSheet && slot != null && userProfile != null) {
        ModalBottomSheet(onDismissRequest = { showSettingsSheet = false }) {
            SlotSettingsSheet(
                slot = slot,
                profile = userProfile!!,
                onUpdate = { key: String, value: Boolean? ->
                    userViewModel.updateSlotPreferences(roomDbId, slotId, key, value)
                },
                onApplyToAll = {
                    userViewModel.applySlotSettingsToAll(roomDbId, slotId)
                    showSettingsSheet = false
                }
            )
        }
    }

    if (showAddThresholdDialog) {
        AddThresholdDialog(
            availableItems = availableItems,
            onDismiss = { showAddThresholdDialog = false },
            onConfirm = { itemName, threshold ->
                userViewModel.saveSlotThreshold(roomDbId, slotId, itemName, threshold)
                showAddThresholdDialog = false
            }
        )
    }
}

@Composable
fun InfoItem(modifier: Modifier = Modifier, label: String, value: String) {
    Column(modifier = modifier) {
        Text(text = label, style = MaterialTheme.typography.labelSmall, color = Color.Gray, fontWeight = FontWeight.Bold)
        Text(text = value, style = MaterialTheme.typography.bodyLarge, color = Color.White, fontWeight = FontWeight.Medium)
    }
}

@Composable
fun ActionCard(icon: ImageVector, title: String, subtitle: String, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = Color(0xFF1E1E24)),
        shape = RoundedCornerShape(16.dp)
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier.size(40.dp).background(Color.White.copy(alpha = 0.05f), CircleShape),
                contentAlignment = Alignment.Center
            ) {
                Icon(icon, null, modifier = Modifier.size(20.dp), tint = Color.White)
            }
            Spacer(Modifier.width(16.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold, color = Color.White)
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = Color.Gray)
            }
            Icon(Icons.Default.ChevronRight, null, tint = Color.Gray)
        }
    }
}

@Composable
fun ThresholdRow(threshold: SlotItemThreshold, onDelete: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(Icons.Outlined.Notifications, null, modifier = Modifier.size(20.dp), tint = Color.Gray)
        Spacer(Modifier.width(16.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(threshold.item_name, style = MaterialTheme.typography.bodyLarge, color = Color.White)
            Text("Notify at ${threshold.threshold} received", style = MaterialTheme.typography.bodySmall, color = Color.Gray)
        }
        IconButton(onClick = onDelete) {
            Icon(Icons.Default.Delete, null, tint = Color(0xFFCF6679), modifier = Modifier.size(20.dp))
        }
    }
}

@Composable
fun AddThresholdDialog(availableItems: List<String>, onDismiss: () -> Unit, onConfirm: (String, Int) -> Unit) {
    var filter by remember { mutableStateOf("") }
    var selectedItem by remember { mutableStateOf("") }
    var threshold by remember { mutableStateOf("1") }
    
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add Threshold") },
        text = {
            Column {
                OutlinedTextField(
                    value = filter, 
                    onValueChange = { filter = it }, 
                    label = { Text("Search Item") },
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(8.dp))
                LazyColumn(modifier = Modifier.heightIn(max = 200.dp)) {
                    val filtered = availableItems.filter { it.contains(filter, ignoreCase = true) }.take(50)
                    items(filtered) { item ->
                        Text(
                            item, 
                            modifier = Modifier.fillMaxWidth().clickable { selectedItem = item; filter = item }.padding(12.dp),
                            color = if (selectedItem == item) MaterialTheme.colorScheme.primary else Color.Unspecified
                        )
                    }
                }
                Spacer(Modifier.height(16.dp))
                TextField(
                    value = threshold,
                    onValueChange = { if (it.all { char -> char.isDigit() }) threshold = it },
                    label = { Text("Notify at count") },
                    keyboardOptions = KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            Button(
                onClick = { if (selectedItem.isNotBlank()) onConfirm(selectedItem, threshold.toIntOrNull() ?: 1) },
                enabled = selectedItem.isNotBlank()
            ) { Text("Add") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } }
    )
}

// ... Existing ChatMessageRow remains the same ...
@Composable
fun ChatMessageRow(message: ChatMessage, datapackage: RoomDatapackage? = null) {
    val annotatedString = remember(message, datapackage) {
        buildAnnotatedString {
            message.segments.forEach { segment ->
                var color = when (segment.type) {
                    "player_id" -> Color(0xFFADFF2F)
                    "player_name" -> Color(0xFFADFF2F)
                    "location_id" -> Color(0xFF03A9F4)
                    "location_name" -> Color(0xFF03A9F4)
                    "entrance_name" -> Color(0xFFBB86FC)
                    else -> Color.White
                }
                var text = segment.text
                if (datapackage != null) {
                    when (segment.type) {
                        "player_id" -> text = datapackage.players[segment.text] ?: segment.text
                        "item_id" -> {
                            val slotKey = segment.player?.toString() ?: message.slot?.toString()
                            val checksum = slotKey?.let { datapackage.slot_to_checksum[it] }
                            if (checksum != null) {
                                val fullId = "${checksum}_${segment.text}"
                                text = datapackage.items[fullId] ?: segment.text
                                val flags = datapackage.item_flags[fullId] ?: 0
                                color = when {
                                    (flags and 1) != 0 -> Color(0xFFADFF2F)
                                    (flags and 2) != 0 -> Color(0xFF03A9F4)
                                    (flags and 4) != 0 -> Color(0xFFF44336)
                                    else -> Color(0xFFE91E63)
                                }
                            } else color = Color(0xFFE91E63)
                        }
                        "location_id" -> {
                            val slotKey = segment.player?.toString() ?: message.slot?.toString()
                            val checksum = slotKey?.let { datapackage.slot_to_checksum[it] }
                            if (checksum != null) text = datapackage.locations["${checksum}_${segment.text}"] ?: segment.text
                        }
                    }
                }
                withStyle(style = SpanStyle(color = color)) { append(text) }
            }
        }
    }
    Text(text = annotatedString, fontSize = 13.sp, modifier = Modifier.padding(vertical = 1.dp), lineHeight = 16.sp)
}

fun formatTimestamp(isoString: String?): String {
    if (isoString == null) return "Never"
    return try {
        val instant = Instant.parse(isoString)
        val now = Instant.now()
        val duration = Duration.between(instant, now)
        val seconds = duration.seconds
        when {
            seconds < 60 -> "Just now"
            seconds < 3600 -> "${seconds / 60}m ago"
            seconds < 86400 -> "${seconds / 3600}h ago"
            else -> "${seconds / 86400}d ago"
        }
    } catch (e: DateTimeParseException) {
        isoString
    }
}
