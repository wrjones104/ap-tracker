package com.jones.aptracker.ui

import androidx.compose.animation.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import android.widget.Toast
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
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import android.content.Context
import android.content.ContextWrapper
import android.app.Activity
import android.view.WindowManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import com.jones.aptracker.R
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
import com.jones.aptracker.network.ThresholdGroup
import com.jones.aptracker.network.ThresholdGroupItem
import com.jones.aptracker.network.ThresholdGroupItemRequest
import com.jones.aptracker.network.AutocompleteOption
import com.jones.aptracker.ui.theme.*
import java.time.Duration
import java.time.Instant
import java.time.format.DateTimeParseException

fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SlotDetailScreen(
    roomDbId: Int,
    slotId: Int,
    onBackClick: () -> Unit,
    onNavigateToHistory: (Int, String, String?, String?) -> Unit,
    userViewModel: UserViewModel = viewModel(),
    textClientViewModel: TextClientViewModel = viewModel()
) {
    val room by userViewModel.trackedSlotsByRoom.collectAsState()
    val currentRoom = room.find { it.room_db_id == roomDbId }
    val slot = currentRoom?.tracked_slots?.find { it.slot_id == slotId }
    val userProfile by userViewModel.userProfile.collectAsState()

    var showSettingsSheet by remember { mutableStateOf(false) }
    var showAddThresholdDialog by remember { mutableStateOf(false) }
    var showEditThresholdDialog by remember { mutableStateOf(false) }
    var editingThresholdGroup by remember { mutableStateOf<ThresholdGroup?>(null) }
    var isConsoleExpanded by remember { mutableStateOf(false) }
    var showHintDialog by remember { mutableStateOf(false) }
    var showLocationHintDialog by remember { mutableStateOf(false) }
    var showPasswordDialog by remember { mutableStateOf(false) }
    var password by remember { mutableStateOf<String?>(null) }

    val context = androidx.compose.ui.platform.LocalContext.current
    val passwordManager = remember { com.jones.aptracker.network.PasswordManager(context) }

    LaunchedEffect(currentRoom?.host) {
        currentRoom?.host?.let { host ->
            val saved = passwordManager.getPassword(host)
            if (saved != null && password == null) {
                password = saved
            }
        }
    }
    val messages by textClientViewModel.messages.collectAsState()
    val connectionStatus by textClientViewModel.connectionStatus.collectAsState()
    val textClientError by textClientViewModel.error.collectAsState()
    val availableLocations by textClientViewModel.availableLocations.collectAsState()
    val availableItems by textClientViewModel.availableItems.collectAsState()
    val isAutocompleteLoading by textClientViewModel.isAutocompleteLoading.collectAsState()
    val datapackage by textClientViewModel.datapackage.collectAsState()
    val keepScreenOn by textClientViewModel.keepScreenOn.collectAsState()

    val activity = remember(context) { context.findActivity() }

    DisposableEffect(keepScreenOn, activity) {
        if (keepScreenOn) {
            activity?.window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        } else {
            activity?.window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
        onDispose {
            activity?.window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }

    LaunchedEffect(roomDbId, slotId) {
        userViewModel.fetchThresholdGroups(roomDbId, slotId)
    }

    val thresholdGroups by userViewModel.thresholdGroups.collectAsState()

    val lifecycleOwner = androidx.lifecycle.compose.LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = androidx.lifecycle.LifecycleEventObserver { _, event ->
            if (event == androidx.lifecycle.Lifecycle.Event.ON_STOP) {
                textClientViewModel.onAppBackgrounded()
            } else if (event == androidx.lifecycle.Lifecycle.Event.ON_START) {
                textClientViewModel.onAppForegrounded()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }



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
            containerColor = MaterialTheme.colorScheme.background
        ) { padding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .imePadding()
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp)
            ) {
                // 1. MAIN INFO CARD
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                    shape = RoundedCornerShape(16.dp)
                ) {
                    Column(modifier = Modifier.padding(20.dp)) {
                        val displayName = if (slot.player_alias.isNullOrBlank()) {
                            slot.player_name
                        } else {
                            "${slot.player_alias} (${slot.player_name})"
                        }
                        Text(
                            text = displayName,
                            style = MaterialTheme.typography.headlineMedium,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
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
                Text("Quick Actions", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onBackground)
                Spacer(Modifier.height(12.dp))

                // 2. QUICK ACTIONS
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    ActionCard(
                        icon = Icons.Default.History,
                        title = "View History",
                        subtitle = "See all items received by this slot",
                        onClick = { onNavigateToHistory(currentRoom.room_db_id, currentRoom.room_alias, null, slot?.player_name) }
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
                    Text("Milestone Groups", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onBackground)
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
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                    shape = RoundedCornerShape(16.dp)
                ) {
                    Column(modifier = Modifier.padding(vertical = 8.dp)) {
                        if (thresholdGroups.isEmpty()) {
                            Text(
                                "No milestone groups set",
                                modifier = Modifier.padding(16.dp),
                                style = MaterialTheme.typography.bodyMedium,
                                color = Color.Gray
                            )
                        } else {
                            thresholdGroups.forEachIndexed { index, group ->
                                ThresholdGroupRow(
                                    group = group,
                                    onEdit = {
                                        editingThresholdGroup = group
                                        showEditThresholdDialog = true
                                    },
                                    onDelete = { userViewModel.deleteThresholdGroup(roomDbId, slotId, group.id) }
                                )
                                if (index < thresholdGroups.size - 1) {
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
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
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
                            Icon(Icons.Default.Terminal, null, modifier = Modifier.size(24.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                            Spacer(Modifier.width(16.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text("Text Client", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                
                                // Keep Screen On Toggle
                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    modifier = Modifier
                                        .padding(top = 2.dp)
                                        .clickable(
                                            interactionSource = remember { androidx.compose.foundation.interaction.MutableInteractionSource() },
                                            indication = null
                                        ) { textClientViewModel.setKeepScreenOn(!keepScreenOn) }
                                ) {
                                    Switch(
                                        checked = keepScreenOn,
                                        onCheckedChange = { textClientViewModel.setKeepScreenOn(it) },
                                        modifier = Modifier
                                            .scale(0.6f)
                                            .size(width = 32.dp, height = 24.dp),
                                        colors = SwitchDefaults.colors(
                                            checkedThumbColor = MaterialTheme.colorScheme.primary,
                                            checkedTrackColor = MaterialTheme.colorScheme.primaryContainer
                                        )
                                    )
                                    Spacer(Modifier.width(4.dp))
                                    Text(
                                        stringResource(R.string.keep_screen_on),
                                        style = MaterialTheme.typography.labelSmall,
                                        color = if (keepScreenOn) MaterialTheme.colorScheme.primary else Color.Gray
                                    )
                                }
                            }
                            
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
                                                    password = password
                                                )
                                            },
                                            shape = RoundedCornerShape(24.dp)
                                        ) {
                                            Text("Connect Console")
                                        }
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            TextButton(onClick = { showPasswordDialog = true }) {
                                                Text(
                                                    if (password.isNullOrBlank()) "Use Password" else "Change Password",
                                                    style = MaterialTheme.typography.labelSmall,
                                                    color = if (password.isNullOrBlank()) Color.Gray else MaterialTheme.colorScheme.primary
                                                )
                                            }
                                            if (!password.isNullOrBlank()) {
                                                TextButton(onClick = { 
                                                    password = null 
                                                    currentRoom.host?.let { passwordManager.deletePassword(it) }
                                                }) {
                                                    Text("Clear", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
                                                }
                                            }
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
                                            .background(MaterialTheme.colorScheme.surface, RoundedCornerShape(8.dp))
                                            .padding(8.dp)
                                    ) {
                                        SelectionContainer {
                                            LazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
                                                items(messages, key = { it.id }) { msg ->
                                                    ChatMessageRow(msg, datapackage)
                                                }
                                            }
                                        }
                                    }
                                    
                                    Spacer(Modifier.height(12.dp))
                                    
                                    Row(
                                        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                                    ) {
                                        AssistChip(
                                            onClick = { showHintDialog = true },
                                            label = { Text("!hint", style = MaterialTheme.typography.labelSmall) },
                                            leadingIcon = { Icon(Icons.Default.Help, null, modifier = Modifier.size(16.dp)) },
                                            colors = AssistChipDefaults.assistChipColors(labelColor = MaterialTheme.colorScheme.primary)
                                        )
                                        AssistChip(
                                            onClick = { showLocationHintDialog = true },
                                            label = { Text("!hint_location", style = MaterialTheme.typography.labelSmall) },
                                            leadingIcon = { Icon(Icons.Default.Place, null, modifier = Modifier.size(16.dp)) },
                                            colors = AssistChipDefaults.assistChipColors(labelColor = MaterialTheme.colorScheme.primary)
                                        )
                                        Spacer(Modifier.weight(1f))
                                        AssistChip(
                                            onClick = { textClientViewModel.disconnect() },
                                            label = { Text("Disconnect", style = MaterialTheme.typography.labelSmall) },
                                            leadingIcon = { Icon(Icons.Default.LinkOff, null, modifier = Modifier.size(16.dp)) },
                                            colors = AssistChipDefaults.assistChipColors(labelColor = MaterialTheme.colorScheme.error)
                                        )
                                    }
                                    
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
                                            focusedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
                                            unfocusedTextColor = MaterialTheme.colorScheme.onSurfaceVariant
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
        LaunchedEffect(Unit) {
            if (availableItems.isEmpty()) {
                textClientViewModel.fetchAutocompleteData(roomDbId, slotId, slot?.game, context.applicationContext as? android.app.Application)
            }
        }
        ThresholdGroupSheet(
            title = "Create Milestone Group",
            confirmLabel = "Create",
            availableItems = availableItems,
            isAutocompleteLoading = isAutocompleteLoading,
            onDismiss = { showAddThresholdDialog = false },
            onConfirm = { name, items ->
                userViewModel.createThresholdGroup(roomDbId, slotId, name, items)
                showAddThresholdDialog = false
            }
        )
    }

    val groupToEdit = editingThresholdGroup
    if (showEditThresholdDialog && groupToEdit != null) {
        LaunchedEffect(Unit) {
            if (availableItems.isEmpty()) {
                textClientViewModel.fetchAutocompleteData(roomDbId, slotId, slot?.game, context.applicationContext as? android.app.Application)
            }
        }
        val initialItems = groupToEdit.items.map {
            ThresholdGroupItemRequest(
                item_name = it.item_name,
                quantity = it.quantity,
                is_group = it.is_group
            )
        }
        ThresholdGroupSheet(
            title = "Edit Milestone Group",
            confirmLabel = "Save",
            initialName = groupToEdit.name ?: "",
            initialItems = initialItems,
            availableItems = availableItems,
            isAutocompleteLoading = isAutocompleteLoading,
            onDismiss = {
                showEditThresholdDialog = false
                editingThresholdGroup = null
            },
            onConfirm = { name, items ->
                userViewModel.updateThresholdGroup(roomDbId, slotId, groupToEdit.id, name, items)
                showEditThresholdDialog = false
                editingThresholdGroup = null
            }
        )
    }

    if (showHintDialog) {
        LaunchedEffect(Unit) {
            if (availableItems.isEmpty()) {
                textClientViewModel.fetchAutocompleteData(roomDbId, slotId, slot?.game, context.applicationContext as? android.app.Application)
            }
        }
        SearchableSelectDialog(
            title = "Hint Item",
            options = availableItems,
            isAutocompleteLoading = isAutocompleteLoading,
            onDismiss = { showHintDialog = false },
            onConfirm = { textClientViewModel.sendMessage("!hint $it"); showHintDialog = false }
        )
    }

    if (showLocationHintDialog) {
        LaunchedEffect(Unit) {
            if (availableLocations.isEmpty()) {
                textClientViewModel.fetchAutocompleteData(roomDbId, slotId, slot?.game, context.applicationContext as? android.app.Application)
            }
        }
        SearchableSelectDialog(
            title = "Hint Location",
            options = availableLocations,
            isAutocompleteLoading = isAutocompleteLoading,
            onDismiss = { showLocationHintDialog = false },
            onConfirm = { textClientViewModel.sendMessage("!hint_location $it"); showLocationHintDialog = false }
        )
    }

    if (showPasswordDialog) {
        PasswordInputDialog(
            initialValue = password ?: "",
            onDismiss = { showPasswordDialog = false },
            onConfirm = { newPassword, shouldSave ->
                password = if (newPassword.isBlank()) null else newPassword
                val host = currentRoom?.host
                if (host != null) {
                    if (shouldSave && !newPassword.isBlank()) {
                        passwordManager.savePassword(host, newPassword)
                    } else {
                        passwordManager.deletePassword(host)
                    }
                }
                showPasswordDialog = false 
            }
        )
    }
}

@Composable
fun InfoItem(modifier: Modifier = Modifier, label: String, value: String) {
    Column(modifier = modifier) {
        Text(text = label, style = MaterialTheme.typography.labelSmall, color = Color.Gray, fontWeight = FontWeight.Bold)
        Text(text = value, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant, fontWeight = FontWeight.Medium)
    }
}

@Composable
fun ActionCard(icon: ImageVector, title: String, subtitle: String, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
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
                Icon(icon, null, modifier = Modifier.size(20.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Spacer(Modifier.width(16.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = Color.Gray)
            }
            Icon(Icons.Default.ChevronRight, null, tint = Color.Gray)
        }
    }
}

@Composable
fun ThresholdGroupRow(
    group: ThresholdGroup,
    onEdit: (() -> Unit)? = null,
    onDelete: () -> Unit
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(Icons.Outlined.Notifications, null, modifier = Modifier.size(20.dp), tint = Color.Gray)
        Spacer(Modifier.width(16.dp))
        Column(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    group.name ?: "Unnamed Milestone",
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                if (group.is_triggered) {
                    Spacer(Modifier.width(8.dp))
                    Box(
                        modifier = Modifier
                            .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.2f), RoundedCornerShape(4.dp))
                            .padding(horizontal = 6.dp, vertical = 2.dp)
                    ) {
                        Text(
                            "Triggered",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.primary,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
            }
            Spacer(Modifier.height(4.dp))
            val itemsText = group.items.joinToString(", ") { item ->
                val groupSuffix = if (item.is_group) " (Group)" else ""
                "${item.quantity}× ${item.item_name}$groupSuffix"
            }
            Text(
                itemsText,
                style = MaterialTheme.typography.bodySmall,
                color = Color.Gray
            )
        }
        if (!group.is_triggered && onEdit != null) {
            IconButton(onClick = onEdit) {
                Icon(Icons.Default.Edit, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(20.dp))
            }
        }
        IconButton(onClick = onDelete) {
            Icon(Icons.Default.Delete, null, tint = Color(0xFFCF6679), modifier = Modifier.size(20.dp))
        }
    }
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun ThresholdGroupSheet(
    title: String,
    confirmLabel: String,
    initialName: String = "",
    initialItems: List<ThresholdGroupItemRequest> = emptyList(),
    availableItems: List<AutocompleteOption>,
    isAutocompleteLoading: Boolean = false,
    onDismiss: () -> Unit,
    onConfirm: (String?, List<ThresholdGroupItemRequest>) -> Unit
) {
    var groupName by remember(initialName) { mutableStateOf(initialName) }
    val selectedItems = remember(initialItems) {
        mutableStateListOf<ThresholdGroupItemRequest>().apply { addAll(initialItems) }
    }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val scrollState = rememberScrollState()
    
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .imePadding()
                .verticalScroll(scrollState)
                .padding(horizontal = 24.dp, vertical = 16.dp)
        ) {
            Text(
                title,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurface
            )
            Spacer(Modifier.height(16.dp))
            
            OutlinedTextField(
                value = groupName,
                onValueChange = { groupName = it },
                label = { Text("Group Name (Optional)") },
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(Modifier.height(20.dp))
            
            var itemFilter by remember { mutableStateOf("") }
            var showSuggestions by remember { mutableStateOf(false) }
            
            LaunchedEffect(showSuggestions) {
                if (showSuggestions) {
                    scrollState.animateScrollTo(0)
                }
            }
            
            Box(modifier = Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = itemFilter,
                    onValueChange = {
                        itemFilter = it
                        showSuggestions = it.isNotBlank()
                    },
                    label = { Text("Search Item to Add...") },
                    modifier = Modifier.fillMaxWidth(),
                    trailingIcon = {
                        if (isAutocompleteLoading) {
                            CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                        }
                    }
                )

                val selectedNames = remember(selectedItems.toList()) {
                    selectedItems.map { it.item_name.lowercase() }.toSet()
                }

                val filtered = remember(itemFilter, availableItems, selectedNames) {
                    if (itemFilter.isBlank()) emptyList()
                    else {
                        availableItems.filter {
                            it.name.contains(itemFilter, ignoreCase = true) &&
                            !selectedNames.contains(it.name.lowercase())
                        }.sortedByDescending {
                            it.name.equals(itemFilter, ignoreCase = true)
                        }
                    }
                }

                DropdownMenu(
                    expanded = showSuggestions && itemFilter.isNotBlank() && filtered.isNotEmpty(),
                    onDismissRequest = { showSuggestions = false },
                    properties = androidx.compose.ui.window.PopupProperties(focusable = false),
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(max = 250.dp)
                ) {
                    filtered.forEach { option ->
                        val displayText = if (option.isGroup) "${option.name} (Group)" else option.name
                        DropdownMenuItem(
                            text = { Text(displayText, style = MaterialTheme.typography.bodyMedium) },
                            onClick = {
                                selectedItems.add(
                                    ThresholdGroupItemRequest(
                                        item_name = option.name,
                                        quantity = 1,
                                        is_group = option.isGroup
                                    )
                                )
                                itemFilter = ""
                                showSuggestions = false
                            }
                        )
                    }
                }
            }
            
            Spacer(Modifier.height(20.dp))
            
            Text(
                "Items & Quantities",
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurface
            )
            Spacer(Modifier.height(8.dp))
            
            if (selectedItems.isEmpty()) {
                Text(
                    "No items added yet. Search below to add items.",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.Gray,
                    modifier = Modifier.padding(vertical = 4.dp)
                )
            } else {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.3f), RoundedCornerShape(8.dp))
                        .padding(8.dp)
                ) {
                    selectedItems.forEachIndexed { index, selectedItem ->
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                if (selectedItem.is_group) "${selectedItem.item_name} (Group)" else selectedItem.item_name,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurface,
                                modifier = Modifier.weight(1f)
                            )
                            
                            var qtyText by remember(selectedItem.item_name) { mutableStateOf(selectedItem.quantity.toString()) }
                            OutlinedTextField(
                                value = qtyText,
                                onValueChange = { newValue ->
                                    if (newValue.isEmpty()) {
                                        qtyText = ""
                                        selectedItems[index] = selectedItem.copy(quantity = 0)
                                    } else if (newValue.all { it.isDigit() }) {
                                        qtyText = newValue
                                        val newQty = newValue.toIntOrNull() ?: 0
                                        selectedItems[index] = selectedItem.copy(quantity = newQty)
                                    }
                                },
                                label = { Text("Qty") },
                                keyboardOptions = KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.Number),
                                modifier = Modifier.width(70.dp).padding(horizontal = 4.dp)
                            )
                            
                            IconButton(onClick = { selectedItems.removeAt(index) }) {
                                Icon(Icons.Default.Close, null, tint = Color.Gray, modifier = Modifier.size(20.dp))
                            }
                        }
                    }
                }
            }

            
            Spacer(Modifier.height(24.dp))
            
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End
            ) {
                TextButton(onClick = onDismiss) {
                    Text("Cancel")
                }
                Spacer(Modifier.width(16.dp))
                Button(
                    onClick = { onConfirm(groupName.trim().ifBlank { null }, selectedItems.toList()) },
                    enabled = selectedItems.isNotEmpty() && selectedItems.all { it.quantity >= 1 }
                ) {
                    Text(confirmLabel)
                }
            }
        }
    }
}

@Composable
fun SearchableSelectDialog(
    title: String,
    options: List<AutocompleteOption>,
    isAutocompleteLoading: Boolean = false,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit
) {
    var filter by remember { mutableStateOf("") }
    
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                OutlinedTextField(
                    value = filter, 
                    onValueChange = { filter = it }, 
                    label = { Text("Search...") },
                    modifier = Modifier.fillMaxWidth(),
                    trailingIcon = {
                        if (isAutocompleteLoading) {
                            CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                        }
                    }
                )
                Spacer(Modifier.height(8.dp))
                if (isAutocompleteLoading && options.isEmpty()) {
                    Box(
                        modifier = Modifier.fillMaxWidth().height(100.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator()
                    }
                } else {
                    LazyColumn(modifier = Modifier.heightIn(max = 300.dp)) {
                        val filtered = options.filter {
                            it.name.contains(filter, ignoreCase = true)
                        }.sortedByDescending {
                            it.name.equals(filter, ignoreCase = true)
                        }
                        items(filtered) { option ->
                            val displayText = if (option.isGroup) "${option.name} (Group)" else option.name
                            Text(
                                displayText, 
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable { onConfirm(option.name) }
                                    .padding(12.dp),
                                style = MaterialTheme.typography.bodyMedium
                            )
                        }
                        if (filtered.isEmpty() && options.isNotEmpty()) {
                            item {
                                Text(
                                    "No matches found",
                                    modifier = Modifier.padding(16.dp),
                                    color = Color.Gray,
                                    style = MaterialTheme.typography.bodySmall
                                )
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {},
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } }
    )
}

// ... Existing ChatMessageRow remains the same ...
@Composable
fun ChatMessageRow(message: ChatMessage, datapackage: RoomDatapackage? = null) {
    val clipboardManager = LocalClipboardManager.current
    val context = LocalContext.current
    val defaultTextColor = MaterialTheme.colorScheme.onSurface
    val annotatedString = remember(message, datapackage, defaultTextColor) {
        buildAnnotatedString {
            message.segments.forEach { segment ->
                var fontWeight = FontWeight.Normal
                var color = when (segment.type) {
                    "player_id", "player_name" -> AP_Tan
                    "location_id", "location_name" -> AP_Green
                    "entrance_name" -> AP_Blue
                    else -> defaultTextColor
                }
                
                var text = segment.text
                if (datapackage != null) {
                    when (segment.type) {
                        "player_id" -> text = datapackage.players[segment.text] ?: segment.text
                        "item_id", "item_name" -> {
                            val slotKey = segment.player?.toString() ?: message.slot?.toString()
                            val checksum = slotKey?.let { datapackage.slot_to_checksum[it] }
                            
                            // Prioritize flags from the segment itself, fallback to datapackage
                            val flags = segment.flags ?: (if (checksum != null) datapackage.item_flags["${checksum}_${segment.text}"] else null) ?: 0
                            
                            if (checksum != null && segment.type == "item_id") {
                                text = datapackage.items["${checksum}_${segment.text}"] ?: segment.text
                            }
                            
                            // Archipelago Standards: 0=Cyan, 1=Plum, 2=SlateBlue, 4=Salmon
                            color = when {
                                flags == 0 -> AP_Cyan
                                (flags and 0x01) != 0 -> AP_Plum
                                (flags and 0x02) != 0 -> AP_SlateBlue
                                (flags and 0x04) != 0 -> AP_Salmon
                                else -> AP_Cyan
                            }
                        }
                        "location_id", "location_name" -> {
                            val slotKey = segment.player?.toString() ?: message.slot?.toString()
                            val checksum = slotKey?.let { datapackage.slot_to_checksum[it] }
                            if (checksum != null && segment.type == "location_id") {
                                text = datapackage.locations["${checksum}_${segment.text}"] ?: segment.text
                            }
                        }
                    }
                }
                withStyle(style = SpanStyle(color = color, fontWeight = fontWeight)) { append(text) }
            }
        }
    }
    Text(
        text = annotatedString,
        fontSize = 13.sp,
        modifier = Modifier
            .fillMaxWidth()
            .clickable {
                val textToCopy = annotatedString.text
                if (textToCopy.isNotEmpty()) {
                    clipboardManager.setText(AnnotatedString(textToCopy))
                    Toast.makeText(context, "Line copied to clipboard", Toast.LENGTH_SHORT).show()
                }
            }
            .padding(vertical = 2.dp),
        lineHeight = 16.sp
    )
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

@Composable
fun PasswordInputDialog(
    initialValue: String,
    onDismiss: () -> Unit,
    onConfirm: (String, Boolean) -> Unit
) {
    var text by remember { mutableStateOf(initialValue) }
    var passwordVisible by remember { mutableStateOf(false) }
    var shouldSave by remember { mutableStateOf(true) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Enter Password") },
        text = {
            Column {
                Text(
                    "Enter the password for the Archipelago server.",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.Gray,
                    modifier = Modifier.padding(bottom = 16.dp)
                )
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it },
                    label = { Text("Password") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    visualTransformation = if (passwordVisible) androidx.compose.ui.text.input.VisualTransformation.None else androidx.compose.ui.text.input.PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.Password),
                    trailingIcon = {
                        val image = if (passwordVisible) Icons.Default.Visibility else Icons.Default.VisibilityOff
                        IconButton(onClick = { passwordVisible = !passwordVisible }) {
                            Icon(image, contentDescription = if (passwordVisible) "Hide password" else "Show password")
                        }
                    }
                )
                Spacer(Modifier.height(16.dp))
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.clickable { shouldSave = !shouldSave }
                ) {
                    Checkbox(checked = shouldSave, onCheckedChange = { shouldSave = it })
                    Text("Save password on device", style = MaterialTheme.typography.bodyMedium)
                }
            }
        },
        confirmButton = {
            Button(onClick = { onConfirm(text, shouldSave) }) {
                Text("Confirm")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel")
            }
        }
    )
}
