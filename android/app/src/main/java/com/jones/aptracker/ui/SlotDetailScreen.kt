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
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.automirrored.filled.Help
import androidx.compose.material.icons.automirrored.filled.ArrowBack
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import com.google.accompanist.swiperefresh.SwipeRefresh
import com.google.accompanist.swiperefresh.rememberSwipeRefreshState
import com.jones.aptracker.network.ChatMessage
import com.jones.aptracker.network.CheeseSlotState
import com.jones.aptracker.network.ConnectionStatus
import com.jones.aptracker.network.RoomDatapackage
import com.jones.aptracker.network.TrackMode
import com.jones.aptracker.network.isWatched
import com.jones.aptracker.network.resolveEntityName
import com.jones.aptracker.network.TrackedSlotDetail
import com.jones.aptracker.network.UserProfile
import com.jones.aptracker.network.ThresholdGroup
import com.jones.aptracker.network.ThresholdGroupItem
import com.jones.aptracker.network.ThresholdGroupItemRequest
import com.jones.aptracker.network.CreateThresholdGroupRequest
import com.jones.aptracker.network.AutocompleteOption
import com.jones.aptracker.network.MilestoneTemplate
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
    onNavigateToMilestoneTemplates: () -> Unit = {},
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
    var savingAsTemplateGroup by remember { mutableStateOf<ThresholdGroup?>(null) }
    var templateOverwriteConflict by remember { mutableStateOf<Pair<List<ThresholdGroupItemRequest>, String>?>(null) }
    var showApplyTemplatesSheet by remember { mutableStateOf(false) }
    var showAddMilestoneMenu by remember { mutableStateOf(false) }

    val context = androidx.compose.ui.platform.LocalContext.current
    val passwordManager = remember { com.jones.aptracker.network.PasswordManager(context) }

    // Milestone edits report themselves through these two, and this screen was collecting
    // neither -- so "Added 3 milestone groups. Skipped: 1 already on this slot." went nowhere,
    // and a failed apply closed the sheet in silence. Worse, an uncleared message would surface
    // later, out of context, on whichever screen happened to collect it next.
    val integrationMessage by userViewModel.integrationMessage.collectAsState()
    val userErrorMessage by userViewModel.errorMessage.collectAsState()

    LaunchedEffect(integrationMessage) {
        integrationMessage?.let {
            Toast.makeText(context, it, Toast.LENGTH_SHORT).show()
            userViewModel.clearIntegrationMessage()
        }
    }

    LaunchedEffect(userErrorMessage) {
        userErrorMessage?.let {
            Toast.makeText(context, it, Toast.LENGTH_LONG).show()
            userViewModel.clearErrorMessage()
        }
    }

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
        // Pull the latest tracked-slot data (incl. Cheese state) whenever this
        // screen opens, so it isn't stale from the last time the Slots list loaded.
        userViewModel.fetchTrackedSlots()
    }

    val isRefreshingCheese by userViewModel.isRefreshingCheese.collectAsState()

    val thresholdGroups by userViewModel.thresholdGroups.collectAsState()
    val milestoneTemplates by userViewModel.milestoneTemplates.collectAsState()

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
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                        }
                    }
                )
            },
            containerColor = MaterialTheme.colorScheme.background
        ) { padding ->
            SwipeRefresh(
                state = rememberSwipeRefreshState(isRefreshing = isRefreshingCheese),
                onRefresh = {
                    // If this slot is synced with Cheese Tracker, pull its live state;
                    // otherwise just reload tracked-slot data.
                    if (slot.cheese != null) userViewModel.refreshCheeseFromServer(roomDbId)
                    else userViewModel.fetchTrackedSlots()
                },
                modifier = Modifier.padding(padding)
            ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
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
                        // Same eye, same leading position, same condition as the rooms
                        // list, so a slot that reads as watched there still reads as
                        // watched once you open it. The Cheese Tracker card further down
                        // keeps its own "Watching" chip: that one is not a duplicate of
                        // this, it is what explains why the controls beside it are locked.
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            if (slot.isWatched) {
                                Icon(
                                    imageVector = Icons.Filled.Visibility,
                                    contentDescription = WATCHING_DESCRIPTION,
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.size(24.dp)
                                )
                                Spacer(Modifier.width(8.dp))
                            }
                            Text(
                                text = displayName,
                                style = MaterialTheme.typography.headlineMedium,
                                fontWeight = FontWeight.Bold,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.weight(1f, fill = false)
                            )
                        }
                        Spacer(Modifier.height(20.dp))
                        
                        // INFO GRID
                        Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                            // Both columns are weight(1f), so a value that fills its
                            // half runs straight into the next one with nothing
                            // between them. Mirror the Column's vertical spacing.
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(16.dp)
                            ) {
                                InfoItem(Modifier.weight(1f), "GAME", slot.game ?: "Unknown")
                                InfoItem(Modifier.weight(1f), "ROOM", currentRoom.room_alias)
                            }
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(16.dp)
                            ) {
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

                // 2b. CHEESE TRACKER SECTION (only when synced with Cheese Tracker)
                val cheeseState = slot.cheese
                if (cheeseState != null) {
                    val isSavingCheese by userViewModel.isSavingCheeseSlot.collectAsState()
                    Spacer(Modifier.height(24.dp))
                    CheeseSlotCard(
                        cheese = cheeseState,
                        trackMode = slot.track_mode,
                        isSaving = isSavingCheese,
                        isRefreshing = isRefreshingCheese,
                        onRefresh = { userViewModel.refreshCheeseFromServer(roomDbId) },
                        onProgressionChange = { userViewModel.updateCheeseProgression(roomDbId, slotId, it) },
                        onCompletionChange = { userViewModel.updateCheeseCompletion(roomDbId, slotId, it) },
                        onPingChange = { userViewModel.updateCheesePing(roomDbId, slotId, it) },
                        onStillBk = { userViewModel.stillBk(roomDbId, slotId) },
                        onSaveNotes = { userViewModel.updateCheeseNotes(roomDbId, slotId, it) }
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
                    // Both ways in are labelled and one tap apart, behind a single Add. The
                    // bookmark icon that used to sit here was the only door to templates once a
                    // slot had groups, and an icon that previously meant "manage templates"
                    // reads as anything but "apply several at once".
                    Box {
                        TextButton(onClick = { showAddMilestoneMenu = true }) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Default.Add, null, modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(4.dp))
                                Text("Add")
                                Icon(Icons.Default.ArrowDropDown, null, modifier = Modifier.size(18.dp))
                            }
                        }
                        DropdownMenu(
                            expanded = showAddMilestoneMenu,
                            onDismissRequest = { showAddMilestoneMenu = false }
                        ) {
                            DropdownMenuItem(
                                text = { Text("New milestone group") },
                                leadingIcon = { Icon(Icons.Default.Add, null, modifier = Modifier.size(20.dp)) },
                                onClick = {
                                    showAddMilestoneMenu = false
                                    showAddThresholdDialog = true
                                }
                            )
                            DropdownMenuItem(
                                text = { Text("Apply templates") },
                                leadingIcon = { Icon(Icons.Default.Bookmarks, null, modifier = Modifier.size(20.dp)) },
                                onClick = {
                                    showAddMilestoneMenu = false
                                    showApplyTemplatesSheet = true
                                }
                            )
                        }
                    }
                }

                if (thresholdGroups.isNotEmpty()) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        "Tap Bookmark to save a group's items as a reusable template.",
                        style = MaterialTheme.typography.bodySmall,
                        color = Color.Gray
                    )
                }

                Spacer(Modifier.height(8.dp))

                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                    shape = RoundedCornerShape(16.dp)
                ) {
                    Column(modifier = Modifier.padding(vertical = 8.dp)) {
                        if (thresholdGroups.isEmpty()) {
                            // A fresh slot is where applying a saved set costs the least and
                            // helps the most, so the sheet gets a second, larger door here.
                            Column(modifier = Modifier.padding(16.dp)) {
                                Text(
                                    "No milestone groups set",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = Color.Gray
                                )
                                Spacer(Modifier.height(8.dp))
                                OutlinedButton(onClick = { showApplyTemplatesSheet = true }) {
                                    Icon(Icons.Default.Bookmarks, null, modifier = Modifier.size(18.dp))
                                    Spacer(Modifier.width(8.dp))
                                    Text("Apply templates")
                                }
                            }
                        } else {
                            thresholdGroups.forEachIndexed { index, group ->
                                ThresholdGroupRow(
                                    group = group,
                                    onEdit = {
                                        editingThresholdGroup = group
                                        showEditThresholdDialog = true
                                    },
                                    onSaveAsTemplate = { savingAsTemplateGroup = group },
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
                                                    password = password,
                                                    roomDbId = roomDbId,
                                                    application = context.applicationContext as? android.app.Application
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
                                            leadingIcon = { Icon(Icons.AutoMirrored.Filled.Help, null, modifier = Modifier.size(16.dp)) },
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
                                            }) { Icon(Icons.AutoMirrored.Filled.Send, null, tint = MaterialTheme.colorScheme.primary) }
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
                onUpdateFinishedDefinition = { definition ->
                    userViewModel.updateSlotFinishedDefinition(roomDbId, slotId, definition)
                },
                onApplyToAll = {
                    userViewModel.applySlotSettingsToAll(roomDbId, slotId)
                    showSettingsSheet = false
                }
            )
        }
    }

    if (showApplyTemplatesSheet) {
        LaunchedEffect(Unit) {
            if (availableItems.isEmpty()) {
                textClientViewModel.fetchAutocompleteData(roomDbId, slotId, slot?.game, context.applicationContext as? android.app.Application)
            }
            userViewModel.fetchMilestoneTemplates(slot?.game)
        }
        ApplyTemplatesSheet(
            gameName = slot?.game,
            templates = milestoneTemplates,
            availableItems = availableItems,
            isAutocompleteLoading = isAutocompleteLoading,
            existingGroupNames = remember(thresholdGroups) {
                thresholdGroups.mapNotNull { it.name?.trim()?.lowercase()?.ifBlank { null } }.toSet()
            },
            onManageTemplates = {
                showApplyTemplatesSheet = false
                onNavigateToMilestoneTemplates()
            },
            onDismiss = { showApplyTemplatesSheet = false },
            onApply = { groups ->
                userViewModel.applyMilestoneTemplates(roomDbId, slotId, groups)
                showApplyTemplatesSheet = false
            }
        )
    }

    if (showAddThresholdDialog) {
        LaunchedEffect(Unit) {
            if (availableItems.isEmpty()) {
                textClientViewModel.fetchAutocompleteData(roomDbId, slotId, slot?.game, context.applicationContext as? android.app.Application)
            }
            userViewModel.fetchMilestoneTemplates(slot?.game)
        }
        ThresholdGroupSheet(
            title = "Create Milestone Group",
            confirmLabel = "Create",
            availableItems = availableItems,
            isAutocompleteLoading = isAutocompleteLoading,
            milestoneTemplates = milestoneTemplates,
            allowTemplatePicker = true,
            allowSaveAsTemplateToggle = true,
            onDismiss = { showAddThresholdDialog = false },
            onConfirm = { name, items, saveAsTemplate ->
                userViewModel.createThresholdGroup(roomDbId, slotId, name, items)
                val game = slot?.game
                val templateName = name?.trim()
                if (saveAsTemplate && !game.isNullOrBlank() && !templateName.isNullOrBlank()) {
                    userViewModel.createMilestoneTemplate(
                        name = templateName,
                        gameName = game,
                        items = items,
                        onConflict = { templateOverwriteConflict = items to templateName }
                    )
                }
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
            onConfirm = { name, items, _ ->
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

    val groupToSaveAsTemplate = savingAsTemplateGroup
    if (groupToSaveAsTemplate != null) {
        LaunchedEffect(groupToSaveAsTemplate) {
            userViewModel.fetchMilestoneTemplates(slot?.game)
        }
        SaveAsTemplateDialog(
            initialName = groupToSaveAsTemplate.name ?: "",
            onDismiss = { savingAsTemplateGroup = null },
            onConfirm = { templateName ->
                val game = slot?.game
                savingAsTemplateGroup = null
                if (!game.isNullOrBlank()) {
                    val items = groupToSaveAsTemplate.items.map {
                        ThresholdGroupItemRequest(
                            item_name = it.item_name,
                            quantity = it.quantity,
                            is_group = it.is_group
                        )
                    }
                    userViewModel.createMilestoneTemplate(
                        name = templateName,
                        gameName = game,
                        items = items,
                        onConflict = { templateOverwriteConflict = items to templateName }
                    )
                }
            }
        )
    }

    val conflict = templateOverwriteConflict
    if (conflict != null) {
        val (conflictItems, conflictName) = conflict
        val conflictGameName = slot?.game
        LaunchedEffect(conflict) {
            userViewModel.fetchMilestoneTemplates(conflictGameName)
        }
        val existingTemplate = milestoneTemplates.find {
            it.game_name == conflictGameName && it.name == conflictName
        }
        AlertDialog(
            onDismissRequest = { templateOverwriteConflict = null },
            title = { Text("Template Already Exists") },
            text = {
                Text("A template named \"$conflictName\" already exists for $conflictGameName. Overwrite it?")
            },
            confirmButton = {
                Button(
                    enabled = existingTemplate != null,
                    onClick = {
                        val existing = existingTemplate
                        if (existing != null && conflictGameName != null) {
                            userViewModel.updateMilestoneTemplate(
                                templateId = existing.id,
                                name = conflictName,
                                gameName = conflictGameName,
                                items = conflictItems
                            )
                        }
                        templateOverwriteConflict = null
                    }
                ) {
                    if (existingTemplate == null) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    } else {
                        Text("Overwrite")
                    }
                }
            },
            dismissButton = {
                TextButton(onClick = { templateOverwriteConflict = null }) { Text("Cancel") }
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

// --- Cheese Tracker slot editing ---

data class CheeseStatusOption(val id: String, val label: String, val color: Color)

val CHEESE_PROGRESSION_OPTIONS = listOf(
    CheeseStatusOption("unknown", "Unknown", Color.Gray),
    CheeseStatusOption("unblocked", "Unblocked", Color(0xFF90CAF9)),
    CheeseStatusOption("bk", "BK", Color(0xFFCF6679)),
    CheeseStatusOption("soft_bk", "Soft BK", Color(0xFFFFB74D)),
    CheeseStatusOption("go", "Go Mode", Color(0xFF4CAF50))
)

val CHEESE_COMPLETION_OPTIONS = listOf(
    CheeseStatusOption("incomplete", "Incomplete", Color.Gray),
    CheeseStatusOption("all_checks", "All Checks", Color(0xFF4FC3F7)),
    CheeseStatusOption("goal", "Goal", Color(0xFF4FC3F7)),
    CheeseStatusOption("done", "Done", Color(0xFF4CAF50)),
    CheeseStatusOption("released", "Forfeit", Color.Gray)
)

val CHEESE_PING_OPTIONS = listOf(
    CheeseStatusOption("liberally", "Liberally", Color(0xFF4CAF50)),
    CheeseStatusOption("sparingly", "Sparingly", Color(0xFFFFB74D)),
    CheeseStatusOption("hints", "Hints", Color(0xFFFFB74D)),
    CheeseStatusOption("see_notes", "See Notes", Color(0xFF4FC3F7)),
    CheeseStatusOption("never", "Never", Color(0xFFCF6679))
)

private fun cheeseOptionLabel(options: List<CheeseStatusOption>, id: String?): String =
    options.find { it.id == id }?.label ?: (id ?: "—")

private val CHEESE_BK_IDS = setOf("bk", "soft_bk")
private val CHEESE_COMPLETE_IDS = setOf("done", "released")

@Composable
fun CheeseSlotCard(
    cheese: CheeseSlotState,
    /** "play" | "watch". Watching is read-only on Cheese; see [TrackMode]. */
    trackMode: String,
    isSaving: Boolean,
    isRefreshing: Boolean,
    onRefresh: () -> Unit,
    onProgressionChange: (String) -> Unit,
    onCompletionChange: (String) -> Unit,
    onPingChange: (String) -> Unit,
    onStillBk: () -> Unit,
    onSaveNotes: (String) -> Unit
) {
    // Watching is read-only on Cheese by definition, so the controls stay
    // disabled even in the window where Cheese still reports the slot as ours
    // (a release that has not landed yet). The server enforces the same rule.
    val isWatching = trackMode == TrackMode.WATCH
    val canEdit = cheese.is_mine && !isWatching
    var isExpanded by remember { mutableStateOf(false) }
    var showForfeitConfirm by remember { mutableStateOf(false) }

    val currentProgressionOption = CHEESE_PROGRESSION_OPTIONS.find { it.id == cheese.progression_status }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        shape = RoundedCornerShape(16.dp)
    ) {
        Column(modifier = Modifier.fillMaxWidth()) {
            // Card header: title + status badge + refresh control + expand/collapse toggle
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(16.dp))
                    .clickable { isExpanded = !isExpanded }
                    .padding(horizontal = 20.dp, vertical = 16.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    Text(
                        "Cheese Tracker",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )

                    if (isWatching) {
                        Surface(
                            color = MaterialTheme.colorScheme.outline.copy(alpha = 0.2f),
                            shape = RoundedCornerShape(8.dp)
                        ) {
                            Text(
                                "Watching",
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }

                    if (currentProgressionOption != null && currentProgressionOption.id != "unknown") {
                        Surface(
                            color = currentProgressionOption.color.copy(alpha = 0.2f),
                            shape = RoundedCornerShape(8.dp)
                        ) {
                            Text(
                                currentProgressionOption.label,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                                style = MaterialTheme.typography.labelSmall,
                                color = currentProgressionOption.color,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                }

                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    IconButton(
                        onClick = onRefresh,
                        enabled = !isRefreshing && !isSaving,
                        modifier = Modifier.size(32.dp)
                    ) {
                        if (isRefreshing) {
                            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                        } else {
                            Icon(
                                Icons.Default.Refresh,
                                contentDescription = "Refresh from Cheese Tracker",
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(18.dp)
                            )
                        }
                    }

                    Icon(
                        if (isExpanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                        contentDescription = if (isExpanded) "Collapse Cheese Tracker" else "Expand Cheese Tracker",
                        tint = Color.Gray
                    )
                }
            }

            AnimatedVisibility(visible = isExpanded) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(start = 20.dp, end = 20.dp, bottom = 20.dp)
                ) {
                    if (!canEdit) {
                        Text(
                            "This slot is claimed by someone else on Cheese Tracker, so it's view-only here.",
                            style = MaterialTheme.typography.bodySmall,
                            color = Color.Gray
                        )
                        Spacer(Modifier.height(16.dp))
                    }

                    // --- Status selectors ---
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        CheeseDropdownField(
                            modifier = Modifier.weight(1f),
                            label = "STATUS",
                            selectedId = cheese.progression_status,
                            options = CHEESE_PROGRESSION_OPTIONS,
                            enabled = canEdit && !isSaving,
                            onSelect = { onProgressionChange(it) }
                        )
                        CheeseDropdownField(
                            modifier = Modifier.weight(1f),
                            label = "COMPLETION",
                            selectedId = cheese.completion_status,
                            options = CHEESE_COMPLETION_OPTIONS,
                            enabled = canEdit && !isSaving,
                            onSelect = { selected ->
                                if (selected == "released") showForfeitConfirm = true
                                else onCompletionChange(selected)
                            }
                        )
                    }

                    Spacer(Modifier.height(16.dp))

                    // --- Last checked + Still BK ---
                    val isBk = cheese.progression_status in CHEESE_BK_IDS
                    val isCompleted = cheese.completion_status in CHEESE_COMPLETE_IDS
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("LAST CHECKED", style = MaterialTheme.typography.labelSmall, color = Color.Gray, fontWeight = FontWeight.Bold)
                            Text(
                                formatTimestamp(cheese.last_checked ?: cheese.last_activity),
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                fontWeight = FontWeight.Medium
                            )
                        }
                        if (canEdit && isBk && !isCompleted) {
                            OutlinedButton(
                                onClick = onStillBk,
                                enabled = !isSaving,
                                shape = RoundedCornerShape(24.dp)
                            ) {
                                Text("Still BK")
                            }
                        }
                    }

                    Spacer(Modifier.height(16.dp))

                    // --- Ping preference ---
                    if (cheese.global_ping_policy != null) {
                        Text("PING PREFERENCE", style = MaterialTheme.typography.labelSmall, color = Color.Gray, fontWeight = FontWeight.Bold)
                        Text(
                            cheeseOptionLabel(CHEESE_PING_OPTIONS, cheese.discord_ping),
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            fontWeight = FontWeight.Medium
                        )
                        Text(
                            "This tracker uses a global ping policy, so per-slot ping is set by the tracker owner.",
                            style = MaterialTheme.typography.labelSmall,
                            color = Color.Gray,
                            modifier = Modifier.padding(top = 2.dp)
                        )
                    } else {
                        CheeseDropdownField(
                            modifier = Modifier.fillMaxWidth(),
                            label = "PING PREFERENCE",
                            selectedId = cheese.discord_ping,
                            options = CHEESE_PING_OPTIONS,
                            enabled = canEdit && !isSaving,
                            onSelect = { onPingChange(it) }
                        )
                    }

                    Spacer(Modifier.height(20.dp))

                    // --- Notes ---
                    Text("NOTES", style = MaterialTheme.typography.labelSmall, color = Color.Gray, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(8.dp))
                    var notesDraft by remember(cheese.notes) { mutableStateOf(cheese.notes) }
                    val notesChanged = notesDraft != cheese.notes
                    OutlinedTextField(
                        value = notesDraft,
                        onValueChange = { if (it.length <= 5000) notesDraft = it },
                        modifier = Modifier.fillMaxWidth(),
                        enabled = canEdit && !isSaving,
                        placeholder = { Text("Add notes for this slot...") },
                        minLines = 3,
                        shape = RoundedCornerShape(12.dp),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
                            unfocusedTextColor = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    )
                    if (canEdit && notesChanged) {
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                            horizontalArrangement = Arrangement.End
                        ) {
                            TextButton(onClick = { notesDraft = cheese.notes }, enabled = !isSaving) {
                                Text("Cancel")
                            }
                            Spacer(Modifier.width(8.dp))
                            Button(onClick = { onSaveNotes(notesDraft) }, enabled = !isSaving) {
                                Text("Save Notes")
                            }
                        }
                    }
                }
            }
        }
    }

    if (showForfeitConfirm) {
        AlertDialog(
            onDismissRequest = { showForfeitConfirm = false },
            title = { Text("Mark as Forfeit?") },
            text = {
                Text(
                    "Forfeit is permanent on Cheese Tracker — once set, it cannot be changed back through the app or the website. Continue?"
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        showForfeitConfirm = false
                        onCompletionChange("released")
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
                ) {
                    Text("Forfeit")
                }
            },
            dismissButton = {
                TextButton(onClick = { showForfeitConfirm = false }) { Text("Cancel") }
            }
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CheeseDropdownField(
    modifier: Modifier = Modifier,
    label: String,
    selectedId: String?,
    options: List<CheeseStatusOption>,
    enabled: Boolean,
    onSelect: (String) -> Unit
) {
    var expanded by remember { mutableStateOf(false) }
    val selected = options.find { it.id == selectedId }

    Column(modifier = modifier) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = Color.Gray, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(4.dp))
        Box {
            Surface(
                onClick = { if (enabled) expanded = true },
                enabled = enabled,
                shape = RoundedCornerShape(12.dp),
                color = MaterialTheme.colorScheme.surface,
                modifier = Modifier.fillMaxWidth()
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Box(
                        modifier = Modifier
                            .size(10.dp)
                            .clip(CircleShape)
                            .background(selected?.color ?: Color.Gray)
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        selected?.label ?: (selectedId ?: "—"),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.weight(1f)
                    )
                    Icon(
                        Icons.Default.KeyboardArrowDown,
                        null,
                        tint = Color.Gray,
                        modifier = Modifier.size(20.dp)
                    )
                }
            }
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                options.forEach { option ->
                    DropdownMenuItem(
                        text = {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Box(
                                    modifier = Modifier
                                        .size(10.dp)
                                        .clip(CircleShape)
                                        .background(option.color)
                                )
                                Spacer(Modifier.width(8.dp))
                                Text(option.label)
                            }
                        },
                        onClick = {
                            expanded = false
                            if (option.id != selectedId) onSelect(option.id)
                        }
                    )
                }
            }
        }
    }
}

@Composable
fun ThresholdGroupRow(
    group: ThresholdGroup,
    onEdit: (() -> Unit)? = null,
    onSaveAsTemplate: (() -> Unit)? = null,
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
                // The name is weighted and the badge is not, so Row measures the
                // badge at its intrinsic width first and the name takes what is
                // left. Unweighted, the name claimed the whole row and squeezed
                // "Triggered" into a one-character-per-line vertical strip.
                Text(
                    group.name ?: "Unnamed Milestone",
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false)
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
                            fontWeight = FontWeight.Bold,
                            maxLines = 1,
                            softWrap = false
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
        if (onSaveAsTemplate != null) {
            IconButton(onClick = onSaveAsTemplate) {
                Icon(Icons.Default.BookmarkAdd, contentDescription = "Save as Template", tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(20.dp))
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
    milestoneTemplates: List<MilestoneTemplate> = emptyList(),
    allowTemplatePicker: Boolean = false,
    allowSaveAsTemplateToggle: Boolean = false,
    nameRequired: Boolean = false,
    onDismiss: () -> Unit,
    onConfirm: (String?, List<ThresholdGroupItemRequest>, Boolean) -> Unit
) {
    var groupName by remember(initialName) { mutableStateOf(initialName) }
    val selectedItems = remember(initialItems) {
        mutableStateListOf<ThresholdGroupItemRequest>().apply { addAll(initialItems) }
    }
    var showTemplatePicker by remember { mutableStateOf(false) }
    var templateDiffNote by remember { mutableStateOf<String?>(null) }
    var saveAsTemplateChecked by remember { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val scrollState = rememberScrollState()

    fun applyTemplate(template: MilestoneTemplate) {
        val (items, note) = resolveTemplateItems(template.items, availableItems)
        groupName = template.name
        selectedItems.clear()
        selectedItems.addAll(items)
        templateDiffNote = note
        showTemplatePicker = false
    }

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

            if (allowTemplatePicker && milestoneTemplates.isNotEmpty()) {
                OutlinedButton(
                    onClick = { showTemplatePicker = true },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Icon(Icons.Default.ContentCopy, null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("Start from a template")
                }
                Spacer(Modifier.height(16.dp))
            }

            OutlinedTextField(
                value = groupName,
                onValueChange = { groupName = it },
                label = { Text(if (nameRequired) "Template Name" else "Group Name (Optional)") },
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

            templateDiffNote?.let { note ->
                Text(
                    note,
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.Gray,
                    modifier = Modifier.padding(bottom = 8.dp)
                )
            }

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

            if (allowSaveAsTemplateToggle) {
                Spacer(Modifier.height(16.dp))
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { saveAsTemplateChecked = !saveAsTemplateChecked },
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Checkbox(checked = saveAsTemplateChecked, onCheckedChange = { saveAsTemplateChecked = it })
                    Spacer(Modifier.width(4.dp))
                    Column {
                        Text(
                            "Also save as a template",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface
                        )
                        Text(
                            "Reuse these items later on another slot for this game.",
                            style = MaterialTheme.typography.bodySmall,
                            color = Color.Gray
                        )
                    }
                }
                if (saveAsTemplateChecked && groupName.isBlank()) {
                    Text(
                        "Enter a name above to save as a template.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(start = 48.dp, top = 2.dp)
                    )
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
                    onClick = { onConfirm(groupName.trim().ifBlank { null }, selectedItems.toList(), saveAsTemplateChecked) },
                    enabled = selectedItems.isNotEmpty() &&
                        selectedItems.all { it.quantity >= 1 } &&
                        (!nameRequired || groupName.isNotBlank()) &&
                        (!saveAsTemplateChecked || groupName.isNotBlank())
                ) {
                    Text(confirmLabel)
                }
            }
        }
    }

    if (showTemplatePicker) {
        AlertDialog(
            onDismissRequest = { showTemplatePicker = false },
            title = { Text("Start from a Template") },
            text = {
                LazyColumn(modifier = Modifier.heightIn(max = 350.dp)) {
                    items(milestoneTemplates) { template ->
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { applyTemplate(template) }
                                .padding(vertical = 10.dp)
                        ) {
                            Text(
                                template.name,
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onSurface
                            )
                            val summary = template.items.joinToString(", ") { "${it.item_name} x${it.quantity}" }
                            Text(
                                summary,
                                style = MaterialTheme.typography.bodySmall,
                                color = Color.Gray,
                                maxLines = 2
                            )
                        }
                        HorizontalDivider(color = Color.DarkGray.copy(alpha = 0.3f))
                    }
                }
            },
            confirmButton = {},
            dismissButton = { TextButton(onClick = { showTemplatePicker = false }) { Text("Cancel") } }
        )
    }
}

/**
 * How one template lands on this slot, worked out before anything is created.
 *
 * The single-group editor could show a template's fallout after the fact, because there was
 * only ever one. Ticking three at once has no such moment -- so every row states up front what
 * it will actually add, and rows that would add nothing usable cannot be ticked at all.
 */
private data class TemplateApplyState(
    val template: MilestoneTemplate,
    val items: List<ThresholdGroupItemRequest>,
    val note: String?,
    val isDuplicate: Boolean
) {
    val isSelectable: Boolean get() = items.isNotEmpty() && !isDuplicate

    val statusText: String? get() = when {
        isDuplicate -> "Already on this slot"
        items.isEmpty() -> "No items from this template are in this seed"
        else -> note
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ApplyTemplatesSheet(
    gameName: String?,
    templates: List<MilestoneTemplate>,
    availableItems: List<AutocompleteOption>,
    isAutocompleteLoading: Boolean,
    existingGroupNames: Set<String>,
    onManageTemplates: () -> Unit,
    onDismiss: () -> Unit,
    onApply: (List<CreateThresholdGroupRequest>) -> Unit
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val selectedIds = remember { mutableStateListOf<Int>() }

    val states = remember(templates, availableItems, existingGroupNames) {
        templates.map { template ->
            val (items, note) = resolveTemplateItems(template.items, availableItems)
            TemplateApplyState(
                template = template,
                items = items,
                note = note,
                isDuplicate = template.name.trim().lowercase() in existingGroupNames
            )
        }
    }

    // Keep the selection honest when the item list finally arrives and re-resolves the rows:
    // a template that was tickable against an unverified list may not be against the real one.
    LaunchedEffect(states) {
        selectedIds.retainAll { id -> states.any { it.template.id == id && it.isSelectable } }
    }

    val isResolving = availableItems.isEmpty() && isAutocompleteLoading

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(horizontal = 24.dp, vertical = 16.dp)
        ) {
            Text(
                "Apply Templates",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurface
            )
            Spacer(Modifier.height(4.dp))
            Text(
                if (gameName.isNullOrBlank()) "Each template becomes its own milestone group."
                else "Each template becomes its own milestone group for $gameName.",
                style = MaterialTheme.typography.bodySmall,
                color = Color.Gray
            )
            Spacer(Modifier.height(16.dp))

            when {
                isResolving -> {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(12.dp))
                        Text(
                            "Checking templates against this seed...",
                            style = MaterialTheme.typography.bodySmall,
                            color = Color.Gray
                        )
                    }
                }
                templates.isEmpty() -> {
                    Text(
                        if (gameName.isNullOrBlank()) "You haven't saved any templates yet."
                        else "You haven't saved any templates for $gameName yet.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Color.Gray
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Tap the bookmark on a milestone group to save it as one.",
                        style = MaterialTheme.typography.bodySmall,
                        color = Color.Gray
                    )
                }
                else -> {
                    LazyColumn(modifier = Modifier.heightIn(max = 420.dp)) {
                        items(states, key = { it.template.id }) { state ->
                            ApplyTemplateRow(
                                state = state,
                                isChecked = state.template.id in selectedIds,
                                onCheckedChange = { checked ->
                                    if (checked) selectedIds.add(state.template.id)
                                    else selectedIds.remove(state.template.id)
                                }
                            )
                            HorizontalDivider(color = Color.DarkGray.copy(alpha = 0.3f))
                        }
                    }
                }
            }

            Spacer(Modifier.height(16.dp))
            HorizontalDivider(color = Color.DarkGray.copy(alpha = 0.3f))
            TextButton(onClick = onManageTemplates) {
                Text("Manage templates")
            }

            Spacer(Modifier.height(8.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically
            ) {
                TextButton(onClick = onDismiss) { Text("Cancel") }
                Spacer(Modifier.width(16.dp))
                Button(
                    onClick = {
                        val chosen = states.filter { it.template.id in selectedIds }
                        onApply(chosen.map { CreateThresholdGroupRequest(it.template.name, it.items) })
                    },
                    enabled = selectedIds.isNotEmpty()
                ) {
                    Text(
                        when (selectedIds.size) {
                            0 -> "Add"
                            1 -> "Add 1 group"
                            else -> "Add ${selectedIds.size} groups"
                        }
                    )
                }
            }
        }
    }
}

@Composable
private fun ApplyTemplateRow(
    state: TemplateApplyState,
    isChecked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    val enabled = state.isSelectable
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .then(
                if (enabled) Modifier.clickable { onCheckedChange(!isChecked) } else Modifier
            )
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Checkbox(
            checked = isChecked,
            onCheckedChange = if (enabled) onCheckedChange else null,
            enabled = enabled
        )
        Spacer(Modifier.width(4.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                state.template.name,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold,
                color = if (enabled) MaterialTheme.colorScheme.onSurface else Color.Gray
            )
            Text(
                state.items.ifEmpty { state.template.items.map {
                    ThresholdGroupItemRequest(it.item_name, it.quantity, it.is_group)
                } }.joinToString(", ") { "${it.item_name} x${it.quantity}" },
                style = MaterialTheme.typography.bodySmall,
                color = Color.Gray,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
            state.statusText?.let { status ->
                Text(
                    status,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (enabled) MaterialTheme.colorScheme.tertiary
                            else MaterialTheme.colorScheme.error
                )
            }
        }
    }
}

private fun resolveTemplateItems(
    templateItems: List<ThresholdGroupItem>,
    availableItems: List<AutocompleteOption>
): Pair<List<ThresholdGroupItemRequest>, String?> {
    if (availableItems.isEmpty()) {
        val items = templateItems.map {
            ThresholdGroupItemRequest(it.item_name, it.quantity, it.is_group)
        }
        return items to "Couldn't verify these items against this version."
    }

    val byLowerName = availableItems.associateBy { it.name.lowercase() }
    val matched = mutableListOf<ThresholdGroupItemRequest>()
    var missingCount = 0
    templateItems.forEach { templateItem ->
        val match = byLowerName[templateItem.item_name.lowercase()]
        if (match != null) {
            matched.add(ThresholdGroupItemRequest(match.name, templateItem.quantity, match.isGroup))
        } else {
            missingCount++
        }
    }

    val note = if (missingCount > 0) {
        val itemWord = if (missingCount == 1) "item isn't" else "items aren't"
        "$missingCount $itemWord in this version and ${if (missingCount == 1) "was" else "were"} left out."
    } else {
        null
    }
    return matched to note
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
                            
                            // Flags come from the PrintJSON segment. There is no
                            // datapackage fallback: flags belong to an item
                            // instance, not to an item type, so the datapackage
                            // has nothing to fall back to.
                            val flags = segment.flags ?: 0

                            if (checksum != null && segment.type == "item_id") {
                                text = resolveEntityName(datapackage.items, checksum, datapackage.generic_checksum, segment.text)
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
                                text = resolveEntityName(datapackage.locations, checksum, datapackage.generic_checksum, segment.text)
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

@Composable
fun SaveAsTemplateDialog(
    initialName: String,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit
) {
    var name by remember { mutableStateOf(initialName) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Save as Template") },
        text = {
            Column {
                Text(
                    "Save this milestone group's items as a reusable template for this game.",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.Gray,
                    modifier = Modifier.padding(bottom = 16.dp)
                )
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Template Name") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )
            }
        },
        confirmButton = {
            Button(
                onClick = { onConfirm(name.trim()) },
                enabled = name.isNotBlank()
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
