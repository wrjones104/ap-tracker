package com.jones.aptracker.ui

import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DragHandle
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import com.google.accompanist.swiperefresh.SwipeRefresh
import com.google.accompanist.swiperefresh.rememberSwipeRefreshState
import com.jones.aptracker.R
import com.jones.aptracker.network.Room
import com.jones.aptracker.network.UserProfile
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.launch
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Warning
import androidx.compose.ui.window.Dialog

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RoomsScreen(
    roomsViewModel: RoomsViewModel = viewModel(),
    userViewModel: UserViewModel = viewModel(),
    onRoomClick: (Int, String) -> Unit,
    onManageSlotsClick: (Int, String) -> Unit
) {
    val rooms by roomsViewModel.rooms.collectAsState()
    val isLoading by roomsViewModel.isLoading.collectAsState()
    val userProfile by userViewModel.userProfile.collectAsState()
    val isSyncingCheese by roomsViewModel.isSyncingCheese.collectAsState()
    val isAutoSyncEnabled by roomsViewModel.isAutoSyncEnabled.collectAsState(initial = true)
    val errorMessage by roomsViewModel.errorMessage.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val lifecycleOwner = LocalLifecycleOwner.current

    // --- Lifecycle & Data Loading ---
    LaunchedEffect(lifecycleOwner) {
        lifecycleOwner.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            roomsViewModel.fetchRooms()
            userViewModel.fetchUserProfile()
        }
    }

    LaunchedEffect(snackbarHostState, roomsViewModel) {
        snapshotFlow { errorMessage }
            .filterNotNull()
            .collect { message ->
                snackbarHostState.showSnackbar(message, duration = SnackbarDuration.Short)
                roomsViewModel.clearErrorMessage()
            }
    }

    // --- State Variables ---
    var roomToDelete by remember { mutableStateOf<Room?>(null) }
    var roomToEdit by remember { mutableStateOf<Room?>(null) }
    var roomToArchive by remember { mutableStateOf<Room?>(null) }
    var roomForOptions by remember { mutableStateOf<Room?>(null) }

    // --- Drag and Drop State ---
    var draggingItemIndex by remember { mutableStateOf<Int?>(null) }
    var draggingItemOffset by remember { mutableStateOf(0f) }
    val listState = rememberLazyListState()
    val coroutineScope = rememberCoroutineScope()

    Scaffold(
        snackbarHost = { SnackbarHost(hostState = snackbarHostState) },

    ) { innerPadding ->
        SwipeRefresh(
            state = rememberSwipeRefreshState(isRefreshing = isLoading),
            onRefresh = {
                roomsViewModel.refreshAll(isCheeseConnected = userProfile?.is_cheese_connected == true)
                userViewModel.fetchTrackedSlots()
                userViewModel.fetchUserProfile()
            },
            modifier = Modifier.padding(top = innerPadding.calculateTopPadding())
        ) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                if (isLoading && rooms.isEmpty()) {
                    CircularProgressIndicator()
                } else if (rooms.isEmpty()) {
                    // --- Empty State Banner ---
                    Box(modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
                        val bannerImages = listOf(R.drawable.room_1, R.drawable.room_2, R.drawable.room_3)
                        val randomBanner by remember { mutableStateOf(bannerImages.random()) }
                        Image(
                            painter = painterResource(id = randomBanner),
                            contentDescription = "Empty Banner",
                            modifier = Modifier
                                .fillMaxWidth(0.95f)
                                .padding(bottom = 8.dp)
                                .align(Alignment.TopCenter)
                                .clip(RoundedCornerShape(8.dp)),
                            contentScale = ContentScale.FillWidth
                        )
                        Text(
                            text = "No rooms found. Tap the '+' to add a room.",
                            modifier = Modifier.align(Alignment.Center)
                        )
                    }
                } else {
                    // --- List with Drag & Drop ---
                    LazyColumn(
                        state = listState,
                        modifier = Modifier
                            .fillMaxSize()
                            .pointerInput(Unit) {
                                detectDragGesturesAfterLongPress(
                                    onDragStart = { offset ->
                                        listState.layoutInfo.visibleItemsInfo
                                            .firstOrNull { item ->
                                                offset.y.toInt() in item.offset..(item.offset + item.size)
                                            }?.let { item ->
                                                if (item.index > 0) { // Prevent dragging Banner (Index 0)
                                                    draggingItemIndex = item.index
                                                    draggingItemOffset = 0f
                                                }
                                            }
                                    },
                                    onDrag = { change, dragAmount ->
                                        change.consume()
                                        draggingItemOffset += dragAmount.y

                                        val currentDraggingIndex = draggingItemIndex ?: return@detectDragGesturesAfterLongPress
                                        val currentItemInfo = listState.layoutInfo.visibleItemsInfo
                                            .firstOrNull { it.index == currentDraggingIndex } ?: return@detectDragGesturesAfterLongPress

                                        val startOffset = currentItemInfo.offset + draggingItemOffset
                                        val centerOffset = (startOffset + (currentItemInfo.size / 2)).toInt()

                                        val targetItem = listState.layoutInfo.visibleItemsInfo
                                            .firstOrNull {
                                                it.index != currentDraggingIndex &&
                                                        it.index > 0 && // Cannot swap with Banner
                                                        centerOffset in it.offset..(it.offset + it.size)
                                            }

                                        if (targetItem != null) {
                                            val fromDataIndex = currentDraggingIndex - 1
                                            val toDataIndex = targetItem.index - 1

                                            if (fromDataIndex >= 0 && toDataIndex >= 0) {
                                                val newLogicalOffset = if (targetItem.index > currentDraggingIndex) {
                                                    currentItemInfo.offset + targetItem.size
                                                } else {
                                                    targetItem.offset
                                                }
                                                val adjustment = currentItemInfo.offset - newLogicalOffset

                                                roomsViewModel.reorderRooms(fromDataIndex, toDataIndex)
                                                draggingItemIndex = targetItem.index
                                                draggingItemOffset += adjustment
                                            }
                                        }

                                        // Auto-scroll
                                        val overscrollThreshold = 150f
                                        val endOffset = startOffset + currentItemInfo.size
                                        if (startOffset < 0) {
                                            coroutineScope.launch { listState.scrollBy(-overscrollThreshold / 5) }
                                        } else if (endOffset > listState.layoutInfo.viewportEndOffset) {
                                            coroutineScope.launch { listState.scrollBy(overscrollThreshold / 5) }
                                        }
                                    },
                                    onDragEnd = {
                                        draggingItemIndex = null
                                        draggingItemOffset = 0f
                                    },
                                    onDragCancel = {
                                        draggingItemIndex = null
                                        draggingItemOffset = 0f
                                    }
                                )
                            },
                        contentPadding = PaddingValues(start = 8.dp, top = 8.dp, end = 8.dp, 80.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        // --- Banner (Index 0) ---
                        item {
                            val bannerImages = listOf(
                                R.drawable.room_1, R.drawable.room_2, R.drawable.room_3,
                                R.drawable.room_4, R.drawable.room_5, R.drawable.room_6
                            )
                            val randomBanner by remember { mutableStateOf(bannerImages.random()) }
                            Image(
                                painter = painterResource(id = randomBanner),
                                contentDescription = "Room Banner",
                                modifier = Modifier
                                    .fillMaxWidth(0.95f)
                                    .padding(bottom = 8.dp)
                                    .clip(RoundedCornerShape(8.dp)),
                                contentScale = ContentScale.FillWidth
                            )
                            Text(
                                text = "Long-press a room to reorder",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(bottom = 8.dp)
                            )
                        }

                        // --- Rooms (Index 1+) ---
                        itemsIndexed(rooms) { index, room ->
                            val listIndex = index + 1
                            val isDragging = listIndex == draggingItemIndex
                            val elevation by animateDpAsState(if (isDragging) 8.dp else 2.dp, label = "elevation")
                            val scale by animateFloatAsState(if (isDragging) 1.05f else 1.0f, label = "scale")

                            Card(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 4.dp)
                                    .zIndex(if (isDragging) 1f else 0f)
                                    .graphicsLayer {
                                        translationY = if (isDragging) draggingItemOffset else 0f
                                        scaleX = scale
                                        scaleY = scale
                                        alpha = if (isDragging) 0.9f else 1f
                                    }
                                    .clickable { onRoomClick(room.id, room.alias) },
                                elevation = CardDefaults.cardElevation(defaultElevation = elevation)
                            ) {
                                Row(
                                    modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 4.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Icon(
                                        imageVector = getIconByName(room.icon_name),
                                        contentDescription = "Icon",
                                        modifier = Modifier.size(24.dp)
                                    )
                                    Spacer(Modifier.width(16.dp))
                                    Column(modifier = Modifier.weight(1f).padding(vertical = 12.dp)) {
                                        Text(text = room.alias, style = MaterialTheme.typography.titleMedium)
                                        Spacer(modifier = Modifier.height(4.dp))
                                        Text(
                                            text = room.host ?: "Connecting...",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = Color.Gray
                                        )
                                        Text(
                                            text = "${room.tracked_slots_count} / ${room.total_slots_count} slots tracked",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = Color.Gray
                                        )
                                    }
                                    IconButton(onClick = { roomForOptions = room }) {
                                        Icon(
                                            imageVector = Icons.Default.MoreVert,
                                            contentDescription = "Options",
                                            tint = MaterialTheme.colorScheme.onSurfaceVariant
                                        )
                                    }
                                    Icon(
                                        imageVector = Icons.Default.DragHandle,
                                        contentDescription = "Reorder",
                                        tint = MaterialTheme.colorScheme.outlineVariant,
                                        modifier = Modifier.padding(horizontal = 8.dp)
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }

        // --- Dialogs & Sheets ---

        if (roomForOptions != null) {
            ModalBottomSheet(onDismissRequest = { roomForOptions = null }) {
                RoomOptionsSheet(
                    room = roomForOptions!!,
                    onDismiss = { roomForOptions = null },
                    onEdit = { r ->
                        roomForOptions = null
                        roomToEdit = r
                    },
                    onArchive = { r ->
                        roomForOptions = null
                        roomToArchive = r
                    },
                    onDelete = { r ->
                        roomForOptions = null
                        roomToDelete = r
                    }
                )
            }
        }

        roomToEdit?.let { room ->
            EditRoomDialog(
                room = room,
                onDismiss = { roomToEdit = null },
                onConfirm = { newAlias, newIcon ->
                    roomsViewModel.updateRoom(room.id, newAlias, newIcon)
                    roomToEdit = null
                },
                onManageSlotsClick = {
                    onManageSlotsClick(room.id, room.alias)
                    roomToEdit = null
                }
            )
        }

        roomToArchive?.let { room ->
            AlertDialog(
                onDismissRequest = { roomToArchive = null },
                title = { Text("Archive Room?") },
                text = { Text("Move '${room.alias}' to archive? You can restore it later from Settings.") },
                confirmButton = {
                    Button(onClick = {
                        roomsViewModel.archiveRoom(room.id)
                        roomToArchive = null
                    }) { Text("Archive") }
                },
                dismissButton = {
                    TextButton(onClick = { roomToArchive = null }) { Text("Cancel") }
                }
            )
        }

        roomToDelete?.let { room ->
            AlertDialog(
                onDismissRequest = { roomToDelete = null },
                title = { Text("Delete Room") },
                text = { Text("Are you sure you want to stop tracking '${room.alias}'? This cannot be undone.") },
                confirmButton = {
                    Button(
                        onClick = {
                            roomsViewModel.deleteRoom(room.id)
                            roomToDelete = null
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
                    ) { Text("Delete") }
                },
                dismissButton = {
                    TextButton(onClick = { roomToDelete = null }) { Text("Cancel") }
                }
            )
        }
    }
}

// --- Sub-Composables ---

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RoomOptionsSheet(
    room: Room,
    onDismiss: () -> Unit,
    onEdit: (Room) -> Unit,
    onArchive: (Room) -> Unit,
    onDelete: (Room) -> Unit
) {
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp).navigationBarsPadding().imePadding()) {
        Text(room.alias, style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(bottom = 16.dp))
        HorizontalDivider()

        ListItem(
            headlineContent = { Text("Edit Room") },
            supportingContent = { Text("Change room name, icon, or manage slots") },
            leadingContent = { Icon(Icons.Default.Edit, null, tint = MaterialTheme.colorScheme.primary) },
            modifier = Modifier.clickable { onEdit(room) }
        )
        ListItem(
            headlineContent = { Text("Archive Room") },
            supportingContent = { Text("Stop tracking updates but keep history") },
            leadingContent = { Icon(Icons.Default.Inventory2, null, tint = MaterialTheme.colorScheme.secondary) },
            modifier = Modifier.clickable { onArchive(room) }
        )
        HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))
        ListItem(
            headlineContent = { Text("Delete Room") },
            supportingContent = { Text("Permanently remove all data") },
            leadingContent = { Icon(Icons.Default.Delete, null, tint = MaterialTheme.colorScheme.error) },
            modifier = Modifier.clickable { onDelete(room) }
        )
        Spacer(Modifier.height(16.dp))
    }
}

// --- Dialogs ---

@Composable
fun AddRoomDialog(onDismiss: () -> Unit, onAdd: (String, String, String) -> Unit) {
    var roomUrl by remember { mutableStateOf("") }
    var alias by remember { mutableStateOf("") }
    var selectedIconName by remember { mutableStateOf("default_icon") }
    var showUrlHelp by remember { mutableStateOf(false) }

    // --- VALIDATION LOGIC ---
    // Detects "domain:port" format common in game clients (e.g., archipelago.gg:12345)
    // Logic: No "http", no slashes (implies no path/room ID), and ends in :digits
    val isSocketFormat = remember(roomUrl) {
        val trimmed = roomUrl.trim()
        !trimmed.startsWith("http") && Regex("""^[^/]+:\d+$""").matches(trimmed)
    }

    // Basic sanity check: Is it not blank, and does it look like a domain/url?
    // We check for a dot (e.g. .com, .gg) or localhost
    val isValidUrlFormat = remember(roomUrl) {
        val trimmed = roomUrl.trim()
        trimmed.isNotBlank() && (trimmed.contains(".") || trimmed.contains("localhost"))
    }

    // Button is enabled only if URL looks valid, is NOT a socket string, and alias is set
    val canAdd = isValidUrlFormat && !isSocketFormat && alias.isNotBlank()


    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add New Room") },
        text = {
            Column {
                TextField(
                    value = roomUrl,
                    onValueChange = { roomUrl = it },
                    label = { Text("Room URL") },
                    placeholder = { Text("archipelago.gg/room/...") },
                    singleLine = true,
                    // Highlight error state if user enters socket format
                    isError = isSocketFormat,
                    modifier = Modifier.fillMaxWidth(),
                    trailingIcon = {
                        IconButton(onClick = { showUrlHelp = true }) {
                            Icon(
                                // Use Warning icon if error, otherwise Info
                                imageVector = if (isSocketFormat) Icons.Default.Warning else Icons.Default.Info,
                                contentDescription = "Show URL Help",
                                tint = if (isSocketFormat) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary
                            )
                        }
                    }
                )

                if (isSocketFormat) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = "It looks like you entered a Game Connection string (host:port). please use the Room URL from your browser instead.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(start = 8.dp)
                    )
                }

                Spacer(Modifier.height(8.dp))

                TextField(
                    value = alias,
                    onValueChange = { alias = it },
                    label = { Text("Room Name") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(Modifier.height(16.dp))
                Text("Select Icon", style = MaterialTheme.typography.labelMedium)
                IconPicker(selected = selectedIconName, onSelect = { selectedIconName = it })
            }
        },
        confirmButton = {
            TextButton(
                enabled = canAdd,
                onClick = { onAdd(roomUrl, alias, selectedIconName) }
            ) { Text("Add") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        }
    )

    // --- Visual Help Popup ---
    if (showUrlHelp) {
        Dialog(onDismissRequest = { showUrlHelp = false }) {
            Card(
                shape = RoundedCornerShape(16.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp)
            ) {
                Column(
                    modifier = Modifier.padding(vertical = 16.dp, horizontal = 8.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(
                        text = "Where to find the URL",
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.padding(bottom = 12.dp)
                    )
                    Image(
                        painter = painterResource(id = R.drawable.room_url_help),
                        contentDescription = "URL Location Example",
                        contentScale = ContentScale.Fit,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(8.dp))
                    )
                    Spacer(modifier = Modifier.height(16.dp))
                    Button(onClick = { showUrlHelp = false }) {
                        Text("Got it")
                    }
                }
            }
        }
    }
}

@Composable
fun EditRoomDialog(
    room: Room,
    onDismiss: () -> Unit,
    onConfirm: (String, String) -> Unit,
    onManageSlotsClick: () -> Unit
) {
    var alias by remember { mutableStateOf(room.alias) }
    var selectedIconName by remember { mutableStateOf(room.icon_name) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Edit Room") },
        text = {
            Column {
                TextField(value = alias, onValueChange = { alias = it }, label = { Text("New Room Name") }, modifier = Modifier.fillMaxWidth())
                Spacer(Modifier.height(16.dp))
                Text("Select Icon", style = MaterialTheme.typography.labelMedium)
                IconPicker(selected = selectedIconName, onSelect = { selectedIconName = it })
                Spacer(Modifier.height(16.dp))
                HorizontalDivider()
                Spacer(Modifier.height(16.dp))
                Button(onClick = onManageSlotsClick, modifier = Modifier.fillMaxWidth()) { Text("Manage Slots") }
            }
        },
        confirmButton = {
            TextButton(onClick = { onConfirm(alias, selectedIconName) }, enabled = alias.isNotBlank()) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } }
    )
}

@Composable
fun IconPicker(selected: String, onSelect: (String) -> Unit) {
    Spacer(Modifier.height(8.dp))
    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        items(AppIcons.allIcons.toList()) { (name, icon) ->
            val isSelected = name == selected
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape)
                    .background(if (isSelected) MaterialTheme.colorScheme.primaryContainer else Color.Transparent)
                    .border(1.dp, if (isSelected) MaterialTheme.colorScheme.primary else Color.Gray, CircleShape)
                    .clickable { onSelect(name) },
                contentAlignment = Alignment.Center
            ) {
                Icon(imageVector = icon, contentDescription = name)
            }
        }
    }
}