package com.jones.aptracker.ui

import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.*
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
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RoomsScreen(
    roomsViewModel: RoomsViewModel = viewModel(),
    userViewModel: UserViewModel = viewModel(),
    onRoomClick: (Int, String) -> Unit,
    onManageSlotsClick: (Int, String) -> Unit
    // Removed unused callbacks (onLogout, onSettings, etc.) to clean up
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

    LaunchedEffect(userProfile, isAutoSyncEnabled) {
        if (userProfile?.is_cheese_connected == true && isAutoSyncEnabled) {
            roomsViewModel.refreshAll(isCheeseConnected = true, forceCheeseSync = false)
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
    var showAddDialog by remember { mutableStateOf(false) }
    var roomToDelete by remember { mutableStateOf<Room?>(null) }
    var roomToEdit by remember { mutableStateOf<Room?>(null) }
    var roomToArchive by remember { mutableStateOf<Room?>(null) }
    var roomForOptions by remember { mutableStateOf<Room?>(null) }
    var newRoomAliasToFind by remember { mutableStateOf<String?>(null) }

    // --- Drag and Drop State ---
    var draggingItemIndex by remember { mutableStateOf<Int?>(null) }
    var draggingItemOffset by remember { mutableStateOf(0f) }
    val listState = rememberLazyListState()
    val coroutineScope = rememberCoroutineScope()

    LaunchedEffect(rooms, newRoomAliasToFind) {
        if (newRoomAliasToFind != null) {
            val addedRoom = rooms.find { it.alias == newRoomAliasToFind }
            if (addedRoom != null) {
                onManageSlotsClick(addedRoom.id, addedRoom.alias)
                newRoomAliasToFind = null
            }
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(hostState = snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text("Tracked Rooms") },
                actions = {
                    TopBarStatus(userProfile = userProfile, isSyncingCheese = isSyncingCheese)
                }
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { showAddDialog = true }) {
                Icon(Icons.Default.Add, contentDescription = "Add Room")
            }
        }
    ) { innerPadding ->
        SwipeRefresh(
            state = rememberSwipeRefreshState(isRefreshing = isLoading),
            onRefresh = { roomsViewModel.refreshAll(isCheeseConnected = userProfile?.is_cheese_connected == true) },
            modifier = Modifier.padding(innerPadding)
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
                        contentPadding = PaddingValues(start = 8.dp, top = 8.dp, end = 8.dp, bottom = 96.dp),
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
                    // FIX: We capture 'r' (the room) here and pass it to the state setter
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

        if (showAddDialog) {
            AddRoomDialog(
                onDismiss = { showAddDialog = false },
                onAdd = { url, alias, icon ->
                    roomsViewModel.addRoom(url, alias, icon) { newRoomAliasToFind = alias }
                    showAddDialog = false
                }
            )
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

@Composable
fun TopBarStatus(userProfile: UserProfile?, isSyncingCheese: Boolean) {
    if (userProfile == null || userProfile.is_guest) return

    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(end = 16.dp)) {
        if (userProfile.avatar_url != null) {
            AsyncImage(
                model = userProfile.avatar_url,
                contentDescription = "Profile",
                modifier = Modifier
                    .size(32.dp)
                    .clip(CircleShape)
                    .border(1.dp, MaterialTheme.colorScheme.outlineVariant, CircleShape),
                contentScale = ContentScale.Crop
            )
        } else {
            Icon(Icons.Default.AccountCircle, null, modifier = Modifier.size(32.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }

        if (userProfile.is_cheese_connected || isSyncingCheese) {
            Spacer(modifier = Modifier.width(6.dp))
        }

        if (isSyncingCheese) {
            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
        } else if (userProfile.is_cheese_connected) {
            Icon(Icons.Default.Link, null, modifier = Modifier.size(18.dp), tint = MaterialTheme.colorScheme.primary)
            Text("🧀", style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(start = 4.dp))
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RoomOptionsSheet(
    room: Room,
    onDismiss: () -> Unit,
    onEdit: (Room) -> Unit,
    onArchive: (Room) -> Unit,
    onDelete: (Room) -> Unit
) {
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp).navigationBarsPadding()) {
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

// ... (Keep AddRoomDialog, EditRoomDialog, IconPicker exactly as they were in your uploaded file)

// --- Dialogs ---

@Composable
fun AddRoomDialog(onDismiss: () -> Unit, onAdd: (String, String, String) -> Unit) {
    var roomUrl by remember { mutableStateOf("") }
    var alias by remember { mutableStateOf("") }
    var selectedIconName by remember { mutableStateOf("default_icon") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add New Room") },
        text = {
            Column {
                TextField(value = roomUrl, onValueChange = { roomUrl = it }, label = { Text("Room URL") }, modifier = Modifier.fillMaxWidth())
                Spacer(Modifier.height(8.dp))
                TextField(value = alias, onValueChange = { alias = it }, label = { Text("Room Name") }, modifier = Modifier.fillMaxWidth())
                Spacer(Modifier.height(16.dp))
                Text("Select Icon", style = MaterialTheme.typography.labelMedium)
                IconPicker(selected = selectedIconName, onSelect = { selectedIconName = it })
            }
        },
        confirmButton = {
            TextButton(onClick = { onAdd(roomUrl, alias, selectedIconName) }, enabled = roomUrl.isNotBlank() && alias.isNotBlank()) { Text("Add") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } }
    )
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