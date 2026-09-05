package com.jones.aptracker.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Flag
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material.icons.filled.UnfoldLess
import androidx.compose.material.icons.filled.UnfoldMore
import androidx.compose.material3.FilterChip
import androidx.compose.ui.unit.Dp
import com.jones.aptracker.data.FinishedResolver
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
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
import androidx.compose.foundation.layout.WindowInsets
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DragHandle
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.LinkOff
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
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
import androidx.compose.runtime.mutableStateMapOf
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
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.accompanist.swiperefresh.SwipeRefresh
import com.google.accompanist.swiperefresh.rememberSwipeRefreshState
import com.jones.aptracker.R
import com.jones.aptracker.network.AvailableCheeseRoom
import com.jones.aptracker.network.Room
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.launch
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Warning
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.window.Dialog
import android.content.Intent
import android.net.Uri
import androidx.compose.ui.platform.LocalContext

/** Matches the cooldown RoomsViewModel already applies to its own resume fetch. */
private const val SLOT_FETCH_COOLDOWN_MS = 10_000L

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RoomsScreen(
    roomsViewModel: RoomsViewModel = viewModel(),
    userViewModel: UserViewModel = viewModel(),
    onRoomActivityClick: (Int, String) -> Unit,
    onManageSlotsClick: (Int, String) -> Unit,
    onSlotClick: (roomDbId: Int, slotId: Int) -> Unit
) {
    val rooms by roomsViewModel.rooms.collectAsState()
    val isLoading by roomsViewModel.isLoading.collectAsState()
    val isCheeseConnected by roomsViewModel.isCheeseConnected.collectAsState()
    val availableCheeseRooms by roomsViewModel.availableCheeseRooms.collectAsState()
    val isImportingCheeseRooms by roomsViewModel.isImportingCheeseRooms.collectAsState()
    var showCheeseSuggestions by remember { mutableStateOf(false) }
    val errorMessage by roomsViewModel.errorMessage.collectAsState()
    val slotErrorMessage by userViewModel.errorMessage.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val lifecycleOwner = LocalLifecycleOwner.current

    // --- Slot state (absorbed from the former Slots tab) ---
    val trackedSlotsByRoom by userViewModel.trackedSlotsByRoom.collectAsState()
    val showFinished by userViewModel.slotsShowFinished.collectAsState()
    val finishedResolver by userViewModel.finishedResolver.collectAsState()
    val expandedRoomIds by userViewModel.expandedRoomIds.collectAsState()
    val layoutDensityKey by userViewModel.layoutDensity.collectAsState()
    var searchQuery by remember { mutableStateOf("") }

    // --- Lifecycle & Data Loading ---
    //
    // The slots have to refresh on resume, not just on first composition: the room counts
    // beside them do, and a card whose header updated while its slot list did not is a
    // card contradicting itself. The cooldown is here rather than in fetchTrackedSlots
    // because roughly a dozen callers -- saving a slot selection, most of all -- depend
    // on that call refetching immediately, and a ViewModel-level cooldown would silently
    // swallow those.
    var lastSlotFetch by remember { mutableStateOf(0L) }
    LaunchedEffect(lifecycleOwner) {
        lifecycleOwner.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            roomsViewModel.fetchRooms()
            roomsViewModel.fetchAvailableCheeseRooms()
            userViewModel.fetchUserProfile()
            val now = System.currentTimeMillis()
            if (now - lastSlotFetch > SLOT_FETCH_COOLDOWN_MS) {
                lastSlotFetch = now
                userViewModel.fetchTrackedSlots()
            }
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

    // The slots come from a different ViewModel than the rooms do, and this screen now
    // shows both. Without this, a failed tracked-slots load left every room looking
    // untracked with nothing on screen to say why -- the error was being written to a
    // flow nobody here was reading.
    LaunchedEffect(snackbarHostState, userViewModel) {
        snapshotFlow { slotErrorMessage }
            .filterNotNull()
            .collect { message ->
                snackbarHostState.showSnackbar(message, duration = SnackbarDuration.Short)
                userViewModel.clearErrorMessage()
            }
    }

    // --- State Variables ---
    var roomToDelete by remember { mutableStateOf<Room?>(null) }
    var roomToEdit by remember { mutableStateOf<Room?>(null) }
    var roomToArchive by remember { mutableStateOf<Room?>(null) }
    var roomForOptions by remember { mutableStateOf<Room?>(null) }
    var roomToRevive by remember { mutableStateOf<Room?>(null) }

    // --- Drag and Drop State ---
    var draggingItemIndex by remember { mutableStateOf<Int?>(null) }
    var draggingItemOffset by remember { mutableStateOf(0f) }

    // Every card collapses for the duration of a drag, not just the one being dragged.
    //
    // The reorder algorithm assumes list items are uniform and short. It reads
    // `currentItemInfo.size` for the auto-scroll trigger, and `targetItem.size` to work
    // out where the dragged card lands after a swap. Collapsing only the dragged card
    // fixed the first and left the second: dragging past a 600dp expanded neighbour
    // feeds a 600dp `adjustment` back into draggingItemOffset and throws the card off
    // screen. Worse, with rooms that tall only one or two are in `visibleItemsInfo` at
    // once, so the dragged item can scroll out of it entirely and the gesture dies
    // mid-drag. Uniform headers are the state the algorithm was written for.
    //
    // This is presentation only -- `expandedRoomIds` is untouched, so every room springs
    // back to how the user left it when the finger lifts. A long-press must not cost
    // someone their layout.
    val isReorderInProgress = draggingItemIndex != null

    // Where the pressed card sat before everything collapsed under it.
    //
    // Collapsing on long-press moves the pressed card up by the combined height of every
    // expanded room above it, so it re-lays-out somewhere the finger is not. Holding its
    // pre-collapse position lets the first drag frame put it back under the press point.
    // Consumed once, then cleared.
    var dragAnchorOffset by remember { mutableStateOf<Int?>(null) }
    val listState = rememberLazyListState()
    val coroutineScope = rememberCoroutineScope()

    // The two sources have to be joined here because neither is a superset: the ordered
    // `rooms` list owns sort order, suspension and the room's total slot count, while
    // `trackedSlotsByRoom` owns the slots themselves. They share a primary key.
    val slotGroupsByRoomId = remember(trackedSlotsByRoom, searchQuery, showFinished, finishedResolver) {
        buildRoomSlotGroups(
            trackedSlotsByRoom.filter { !it.is_archived },
            searchQuery,
            showFinished,
            finishedResolver
        ).associateBy { it.room.room_db_id }
    }

    // A blank query shows every room, including one with nothing tracked yet -- that room
    // is precisely the one you opened the screen to fix, and buildRoomSlotGroups drops it
    // (no slots means no matches). Once you are actually searching, a room with no hit is
    // noise and goes.
    val displayRooms = remember(rooms, slotGroupsByRoomId, searchQuery) {
        if (searchQuery.isBlank()) rooms
        else rooms.filter { it.id in slotGroupsByRoomId }
    }

    // Searching changes what the list is, not just what it shows: rooms drop out, and
    // every survivor is force-expanded. Two controls have to stand down for that.
    // Reordering writes back by index into the *unfiltered* list, so it would shuffle the
    // wrong rooms; and expand-all cannot collapse what the search is holding open.
    val isSearching = searchQuery.isNotBlank()

    val allExpanded = remember(expandedRoomIds, displayRooms) {
        displayRooms.isNotEmpty() && displayRooms.all { it.id in expandedRoomIds }
    }

    val metrics = remember(layoutDensityKey) { LayoutDensity.fromKey(layoutDensityKey).metrics }

    Scaffold(
        snackbarHost = { SnackbarHost(hostState = snackbarHostState) },
        contentWindowInsets = WindowInsets(0.dp)
    ) { innerPadding ->
        SwipeRefresh(
            state = rememberSwipeRefreshState(isRefreshing = isLoading),
            onRefresh = {
                roomsViewModel.fetchRooms(force = true)
                userViewModel.fetchTrackedSlots()
                userViewModel.fetchUserProfile()
            },
            modifier = Modifier.padding(innerPadding)
        ) {
          CompositionLocalProvider(LocalLayoutMetrics provides metrics) {
            Column(modifier = Modifier.fillMaxSize()) {
                // Pinned above everything, and outside the list on purpose. As a list item
                // it scrolled away, and it vanished outright whenever a search matched
                // nothing -- the one moment the screen looked broken and most needed to
                // still look like the app. It is chrome, so it lives with the chrome.
                HeroBanner(
                    // Not merely "no rooms": on a cold start that is also true while the
                    // first load is still running, which flashed "add a new room!" above
                    // a spinner at someone who has plenty of rooms.
                    isWelcome = rooms.isEmpty() && !isLoading,
                    metrics = metrics
                )

                // Search and the finished filter reach across every room, so scrolling
                // them away with the rooms would put them out of view exactly when a long
                // list makes them useful.
                if (rooms.isNotEmpty()) {
                    TextField(
                        value = searchQuery,
                        onValueChange = { searchQuery = it },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp, vertical = metrics.chromeVertical),
                        label = { Text("Search by player, alias, or game") },
                        leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                        trailingIcon = {
                            if (searchQuery.isNotEmpty()) {
                                IconButton(onClick = { searchQuery = "" }) {
                                    Icon(Icons.Default.Close, contentDescription = "Clear search")
                                }
                            }
                        },
                        singleLine = true
                    )

                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp, vertical = metrics.chromeVertical / 2),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Row(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            FilterChip(
                                selected = showFinished,
                                onClick = { userViewModel.setSlotsShowFinished(!showFinished) },
                                label = { Text("Show Finished") },
                                leadingIcon = if (showFinished) {
                                    {
                                        Icon(
                                            imageVector = Icons.Default.Flag,
                                            contentDescription = null,
                                            modifier = Modifier.size(16.dp)
                                        )
                                    }
                                } else null
                            )

                            val totalSlots = displayRooms.sumOf {
                                slotGroupsByRoomId[it.id]?.visibleSlots?.size ?: 0
                            }
                            Text(
                                text = if (totalSlots == 1) "1 slot" else "$totalSlots slots",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }

                        // A search forces every matching room open, so the toggle would
                        // claim to do something it cannot. It comes back when you clear.
                        if (!isSearching) {
                            IconButton(onClick = {
                                userViewModel.setAllRoomsExpanded(displayRooms.map { it.id }, !allExpanded)
                            }) {
                                Icon(
                                    imageVector = if (allExpanded) Icons.Default.UnfoldLess else Icons.Default.UnfoldMore,
                                    contentDescription = if (allExpanded) "Collapse All" else "Expand All"
                                )
                            }
                        }
                    }

                    if (!isSearching && metrics.showsReorderHint) {
                        Text(
                            text = "Tap a room for its slots - long-press to reorder",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(bottom = 4.dp),
                            textAlign = TextAlign.Center
                        )
                    }

                    // Rooms waiting on Cheese are offered above the list rather than
                    // appearing in it unannounced. Deliberately not a list item: every
                    // item in the list below is a room, one to one, and the reorder
                    // math depends on that.
                    if (availableCheeseRooms.isNotEmpty() && !isSearching) {
                        CheeseSuggestionsBanner(
                            count = availableCheeseRooms.size,
                            onClick = { showCheeseSuggestions = true }
                        )
                    }
                }

                // weight rather than fillMaxSize: this takes whatever the pinned chrome
                // above it leaves, and stays correct if that chrome grows.
                Box(modifier = Modifier.weight(1f), contentAlignment = Alignment.Center) {
                    if (isLoading && rooms.isEmpty()) {
                        CircularProgressIndicator()
                    } else if (rooms.isEmpty()) {
                        // Nothing here on purpose: the welcome banner above already carries
                        // the "add a room" call to action, and repeating it below just
                        // says the same thing twice on the emptiest screen in the app.
                    } else if (displayRooms.isEmpty()) {
                        Text(
                            text = "No slots match your search.",
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    } else {
                        // --- List with Drag & Drop ---
                        //
                        // Every item in this list is a room, one to one. The banner used to
                        // sit at index 0, which is why the reorder math below no longer
                        // carries the off-by-one it used to: list index *is* room index.
                        LazyColumn(
                            state = listState,
                            modifier = Modifier
                                .fillMaxSize()
                                .then(
                                    if (isSearching) Modifier else Modifier.pointerInput(Unit) {
                                        detectDragGesturesAfterLongPress(
                                            onDragStart = { offset ->
                                                listState.layoutInfo.visibleItemsInfo
                                                    .firstOrNull { item ->
                                                        offset.y.toInt() in item.offset..(item.offset + item.size)
                                                    }?.let { item ->
                                                        draggingItemIndex = item.index
                                                        draggingItemOffset = 0f
                                                        // Read before the collapse this
                                                        // assignment is about to trigger.
                                                        dragAnchorOffset = item.offset
                                                    }
                                            },
                                            onDrag = { change, dragAmount ->
                                                change.consume()
                                                draggingItemOffset += dragAmount.y

                                                val currentDraggingIndex = draggingItemIndex ?: return@detectDragGesturesAfterLongPress
                                                val currentItemInfo = listState.layoutInfo.visibleItemsInfo
                                                    .firstOrNull { it.index == currentDraggingIndex } ?: return@detectDragGesturesAfterLongPress

                                                // First frame after the collapse, which by
                                                // now has reached layout: shift the card
                                                // back to where it was actually pressed.
                                                // Applied before the offsets below are
                                                // derived, so the swap math sees the
                                                // corrected position rather than chasing it
                                                // a frame later. A no-op when nothing above
                                                // the card was expanded.
                                                dragAnchorOffset?.let { anchor ->
                                                    draggingItemOffset += (anchor - currentItemInfo.offset).toFloat()
                                                    dragAnchorOffset = null
                                                }

                                                val startOffset = currentItemInfo.offset + draggingItemOffset
                                                val centerOffset = (startOffset + (currentItemInfo.size / 2)).toInt()

                                                val targetItem = listState.layoutInfo.visibleItemsInfo
                                                    .firstOrNull {
                                                        it.index != currentDraggingIndex &&
                                                                centerOffset in it.offset..(it.offset + it.size)
                                                    }

                                                if (targetItem != null) {
                                                    val newLogicalOffset = if (targetItem.index > currentDraggingIndex) {
                                                        currentItemInfo.offset + targetItem.size
                                                    } else {
                                                        targetItem.offset
                                                    }
                                                    val adjustment = currentItemInfo.offset - newLogicalOffset

                                                    roomsViewModel.reorderRooms(currentDraggingIndex, targetItem.index)
                                                    draggingItemIndex = targetItem.index
                                                    draggingItemOffset += adjustment
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
                                                dragAnchorOffset = null
                                            },
                                            onDragCancel = {
                                                draggingItemIndex = null
                                                draggingItemOffset = 0f
                                                dragAnchorOffset = null
                                            }
                                        )
                                    }
                                ),
                            contentPadding = PaddingValues(
                                start = 8.dp,
                                top = metrics.cardSpacing,
                                end = 8.dp,
                                bottom = 80.dp
                            ),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            itemsIndexed(displayRooms, key = { _, room -> room.id }) { index, room ->
                                val isDragging = index == draggingItemIndex
                                val elevation by animateDpAsState(if (isDragging) 8.dp else 2.dp, label = "elevation")
                                val scale by animateFloatAsState(if (isDragging) 1.05f else 1.0f, label = "scale")

                                RoomCard(
                                    room = room,
                                    group = slotGroupsByRoomId[room.id],
                                    // Searching implies you want to see what matched, so a
                                    // matching room opens regardless of its saved state.
                                    //
                                    isExpanded = isSearching || room.id in expandedRoomIds,
                                    isReorderEnabled = !isSearching,
                                    isDragging = isDragging,
                                    isReorderInProgress = isReorderInProgress,
                                    elevation = elevation,
                                    scale = scale,
                                    // Passed as a lambda, not a Float: read here it would be
                                    // a composition-phase read, recomposing every visible
                                    // card on every frame of the gesture. Called inside
                                    // graphicsLayer it stays a draw-phase read.
                                    dragOffset = { draggingItemOffset },
                                    finishedResolver = finishedResolver,
                                    onToggleExpand = {
                                        userViewModel.setRoomExpanded(room.id, room.id !in expandedRoomIds)
                                    },
                                    onReviveClick = { roomToRevive = room },
                                    onOptionsClick = { roomForOptions = room },
                                    onSlotClick = { slotId -> onSlotClick(room.id, slotId) },
                                    onManageSlotsClick = { onManageSlotsClick(room.id, room.alias) },
                                    onShowFinished = { userViewModel.setSlotsShowFinished(true) }
                                )
                            }
                        }
                    }
                }
            }
          }
        }

        // --- Dialogs & Sheets ---

        if (showCheeseSuggestions) {
            ModalBottomSheet(onDismissRequest = { showCheeseSuggestions = false }) {
                CheeseSuggestionsSheet(
                    available = availableCheeseRooms,
                    isImporting = isImportingCheeseRooms,
                    onAdd = { ids ->
                        showCheeseSuggestions = false
                        roomsViewModel.importCheeseRooms(ids)
                    },
                    onDismissRooms = { ids ->
                        showCheeseSuggestions = false
                        roomsViewModel.dismissCheeseRooms(ids)
                    }
                )
            }
        }

        if (roomForOptions != null) {
            ModalBottomSheet(onDismissRequest = { roomForOptions = null }) {
                RoomOptionsSheet(
                    room = roomForOptions!!,
                    isCheeseConnected = isCheeseConnected,
                    onDismiss = { roomForOptions = null },
                    onViewActivity = { r ->
                        roomForOptions = null
                        onRoomActivityClick(r.id, r.alias)
                    },
                    onManageSlots = { r ->
                        roomForOptions = null
                        onManageSlotsClick(r.id, r.alias)
                    },
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
                    },
                    onRevive = { r ->
                        roomForOptions = null
                        roomToRevive = r
                    },
                    onCheeseLinkChange = { r, linked ->
                        roomForOptions = null
                        roomsViewModel.setRoomCheeseLink(r.id, linked)
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

        roomToRevive?.let { room ->
            val context = LocalContext.current
            AlertDialog(
                onDismissRequest = { roomToRevive = null },
                title = { Text("Room Suspended") },
                text = {
                    Text(
                        "This room is suspended. This can happen if there are communication errors or backend update issues.\n\n" +
                        "To wake it, hit the button below to open the room in a browser, and resume tracking in Archipelago Alerts."
                    )
                },
                confirmButton = {
                    Button(onClick = {
                        val url = room.web_url ?: "https://archipelago.gg/room/${room.room_id}"
                        try {
                            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                        } catch (e: Exception) {
                            e.printStackTrace()
                        }
                        roomsViewModel.reviveRoom(room.id)
                        roomToRevive = null
                    }) {
                        Text("Wake & Revive Room")
                    }
                },
                dismissButton = {
                    Row {
                        TextButton(onClick = {
                            roomToRevive = null
                            onRoomActivityClick(room.id, room.alias)
                        }) {
                            Text("View History")
                        }
                        Spacer(modifier = Modifier.width(8.dp))
                        TextButton(onClick = { roomToRevive = null }) {
                            Text("Cancel")
                        }
                    }
                }
            )
        }
    }
}

// --- Sub-Composables ---

/**
 * The Archipelago Alerts mark, pinned to the top of the rooms screen.
 *
 * One banner for both states rather than two. It used to be two: a tall welcome panel when
 * you had no rooms, and a short strip as the first item of the room list otherwise. That
 * meant the branding scrolled away in normal use and disappeared completely whenever a
 * search matched nothing, which made an ordinary empty result look like a broken screen.
 *
 * [isWelcome] only grows it and adds the call to action; it is the same banner either way.
 */
@Composable
private fun HeroBanner(isWelcome: Boolean, metrics: LayoutMetrics) {
    val height = if (isWelcome) 160.dp else metrics.bannerHeight
    val iconSize = if (isWelcome) 72.dp else metrics.bannerIconSize
    val titleStyle = if (isWelcome) {
        MaterialTheme.typography.headlineMedium
    } else {
        MaterialTheme.typography.headlineSmall
    }
    val outlineWidth = with(LocalDensity.current) { 2.dp.toPx() }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 8.dp, vertical = 4.dp)
            .height(height)
            .clip(RoundedCornerShape(8.dp)),
        contentAlignment = Alignment.Center
    ) {
        Image(
            painter = painterResource(id = R.drawable.bg_banner_gradient),
            contentDescription = null,
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Crop
        )
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(horizontal = 16.dp)
        ) {
            Image(
                painter = painterResource(id = R.drawable.ap_alerts_icon_3),
                contentDescription = "AP Alerts Icon",
                modifier = Modifier.size(iconSize)
            )
            Spacer(Modifier.width(16.dp))
            Column {
                // Drawn twice: a stroked pass behind a filled one, so the wordmark keeps
                // its edge wherever it lands on the gradient.
                Box {
                    Text(
                        text = "Archipelago Alerts",
                        style = titleStyle.copy(
                            color = Color.Black,
                            drawStyle = Stroke(width = outlineWidth, join = StrokeJoin.Round)
                        )
                    )
                    Text(
                        text = "Archipelago Alerts",
                        style = titleStyle.copy(color = Color.White)
                    )
                }
                if (isWelcome) {
                    Text(
                        text = "Click the + button below to add a new room!",
                        style = MaterialTheme.typography.bodyLarge,
                        color = Color.White
                    )
                }
            }
        }
    }
}

/**
 * Says what one room's relationship with Cheese Tracker is, in the smallest
 * space that can carry it.
 *
 * Three states worth a chip: shared, still being created there (the push takes a
 * couple of minutes), and shared but no longer on the user's Cheese dashboard.
 * An app-only room gets nothing, which is the quiet default it should be.
 */
@Composable
private fun CheeseRoomChip(room: Room) {
    if (room.cheese_link != "linked") return

    val (label, color) = when {
        room.cheese_unlisted -> "Not on Cheese" to MaterialTheme.colorScheme.onSurfaceVariant
        room.cheese_tracker_id == null -> "Sharing..." to MaterialTheme.colorScheme.onSurfaceVariant
        else -> "Cheese" to MaterialTheme.colorScheme.primary
    }

    Spacer(Modifier.width(6.dp))
    Text(
        text = "\uD83E\uDDC0 $label",
        style = MaterialTheme.typography.labelSmall,
        color = color
    )
}

/**
 * One room, and — when expanded — the slots it tracks.
 *
 * This card is the whole of the old Rooms and Slots tabs in one place. It exists because
 * those two screens each rendered the same room with the same name, host and a slot count,
 * and then hardwired the tap to a different destination: Rooms went to the activity feed,
 * Slots expanded. Neither guess was reliably the one you wanted, so the tap now does the
 * thing the room *contains* (its slots) and everything else is an explicit control.
 *
 * The two counts are kept side by side on purpose. They answer different questions:
 * "3 of 12 tracked" is about how much of the room you have opted into and is the one that
 * tells you there is more to add; the active/finished bar is about how the slots you did
 * opt into are going.
 */
@Composable
private fun RoomCard(
    room: Room,
    /** Null when the room has no tracked slots at all, or none survived the search. */
    group: RoomSlotGroup?,
    isExpanded: Boolean,
    isReorderEnabled: Boolean,
    isDragging: Boolean,
    /** True while any card is being dragged, including this one. */
    isReorderInProgress: Boolean,
    elevation: Dp,
    scale: Float,
    dragOffset: () -> Float,
    finishedResolver: FinishedResolver,
    onToggleExpand: () -> Unit,
    onReviveClick: () -> Unit,
    onOptionsClick: () -> Unit,
    onSlotClick: (slotId: Int) -> Unit,
    onManageSlotsClick: () -> Unit,
    onShowFinished: () -> Unit
) {
    val visibleSlots = group?.visibleSlots.orEmpty()
    val hiddenFinishedCount = group?.hiddenFinishedCount ?: 0
    val metrics = LocalLayoutMetrics.current
    val showsSlots = isExpanded && !isReorderInProgress

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = metrics.cardSpacing)
            .zIndex(if (isDragging) 1f else 0f)
            .graphicsLayer {
                translationY = if (isDragging) dragOffset() else 0f
                scaleX = scale
                scaleY = scale
                alpha = if (isDragging) 0.9f else 1f
            },
        elevation = CardDefaults.cardElevation(defaultElevation = elevation)
    ) {
        Column {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable(onClick = onToggleExpand)
                    .padding(start = 16.dp, end = 4.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    imageVector = getIconByName(room.icon_name),
                    contentDescription = "Icon",
                    modifier = Modifier.size(24.dp)
                )
                Spacer(Modifier.width(12.dp))
                Column(modifier = Modifier.weight(1f).padding(vertical = metrics.cardHeaderVertical)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(text = room.alias, style = MaterialTheme.typography.titleMedium)
                        if (room.is_suspended) {
                            Spacer(modifier = Modifier.width(8.dp))
                            Box(
                                modifier = Modifier
                                    .background(
                                        color = MaterialTheme.colorScheme.errorContainer,
                                        shape = RoundedCornerShape(4.dp)
                                    )
                                    .border(
                                        width = 0.5.dp,
                                        color = MaterialTheme.colorScheme.error,
                                        shape = RoundedCornerShape(4.dp)
                                    )
                                    .padding(horizontal = 6.dp, vertical = 2.dp)
                            ) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Icon(
                                        imageVector = Icons.Default.Warning,
                                        contentDescription = null,
                                        modifier = Modifier.size(10.dp),
                                        tint = MaterialTheme.colorScheme.error
                                    )
                                    Spacer(modifier = Modifier.width(4.dp))
                                    Text(
                                        text = "Suspended",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onErrorContainer
                                    )
                                }
                            }
                        }
                    }
                    Spacer(modifier = Modifier.height(4.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = room.host ?: "Connecting...",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        // Whether a room is shared on Cheese used to be invisible,
                        // which is part of why rooms vanishing from Cheese felt
                        // arbitrary (#323). No chip means the room is app-only.
                        CheeseRoomChip(room)
                    }
                    // Both slot counts on one line. They were a line each plus a bar on
                    // a third, which is three lines to say two numbers -- and they are
                    // closely enough related ("how much of the room am I watching" and
                    // "how are those going") that reading them together is easier than
                    // reading them stacked.
                    RoomSlotProgress(
                        trackedLabel = "${room.tracked_slots_count} of ${room.total_slots_count} tracked",
                        activeCount = group?.activeCount ?: 0,
                        finishedCount = group?.finishedCount ?: 0
                    )
                }
                Spacer(Modifier.width(4.dp))
                Icon(
                    imageVector = if (showsSlots) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                    contentDescription = if (showsSlots) "Collapse" else "Expand",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant
                )
                IconButton(onClick = onOptionsClick) {
                    Icon(
                        imageVector = Icons.Default.MoreVert,
                        contentDescription = "Options",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                // Hidden while searching, where long-press reordering is switched off:
                // a handle that does nothing is worse than no handle.
                if (isReorderEnabled) {
                    Icon(
                        imageVector = Icons.Default.DragHandle,
                        contentDescription = "Reorder",
                        tint = MaterialTheme.colorScheme.outlineVariant,
                        modifier = Modifier.padding(end = 8.dp)
                    )
                }
            }

            // Removed rather than animated away while reordering. A shrink animation
            // reports a different height every frame, and those are the heights the drag
            // math is reading -- the collapse has to be instant to be useful to it.
            if (!isReorderInProgress) {
                AnimatedVisibility(
                    visible = isExpanded,
                    enter = expandVertically(),
                    exit = shrinkVertically()
                ) {
                    Column {
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

                        // A suspended room used to answer a tap with the revive dialog instead
                        // of opening. That is the same hijacked tap this screen exists to undo,
                        // and it left no way to look at the room's slots at all. The room opens
                        // like any other now; the prompt sits at the top of what you opened.
                        if (room.is_suspended) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable(onClick = onReviveClick)
                                    .padding(
                                        start = metrics.slotIndent,
                                        end = 16.dp,
                                        top = metrics.slotRowVertical,
                                        bottom = metrics.slotRowVertical
                                    ),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Icon(
                                    imageVector = Icons.Default.Link,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.error,
                                    modifier = Modifier.size(18.dp)
                                )
                                Spacer(Modifier.width(8.dp))
                                Text(
                                    text = "Not being polled - tap to revive",
                                    style = MaterialTheme.typography.labelLarge,
                                    color = MaterialTheme.colorScheme.error
                                )
                            }
                        }

                        if (hiddenFinishedCount > 0) {
                            HiddenFinishedSlotsRow(
                                count = hiddenFinishedCount,
                                onShowFinished = onShowFinished
                            )
                        }

                        visibleSlots.forEach { slot ->
                            SlotRow(
                                slot = slot,
                                isFinished = finishedResolver.isFinished(
                                    roomDbId = room.id,
                                    slotId = slot.slot_id,
                                    isGoaled = slot.is_finished,
                                    hasAllChecks = slot.has_all_checks
                                ),
                                onClick = { onSlotClick(slot.slot_id) }
                            )
                        }

                        // A room you have just added expands to nothing at all otherwise,
                        // which reads as a failure rather than as work still to do.
                        if (visibleSlots.isEmpty() && hiddenFinishedCount == 0) {
                            Text(
                                text = "No slots tracked in this room yet.",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(
                                    start = metrics.slotIndent,
                                    end = 16.dp,
                                    top = metrics.slotRowVertical
                                )
                            )
                        }

                        ManageSlotsRow(
                            hasTrackedSlots = room.tracked_slots_count > 0,
                            onClick = onManageSlotsClick
                        )
                    }
                }
            }
        }
    }
}

/**
 * "There are rooms on your Cheese dashboard the app doesn't have."
 *
 * An invitation, not an import. Rooms used to appear in the list unannounced,
 * including ones somebody else had added the user to; now they wait here until
 * someone says yes. See #323.
 */
@Composable
private fun CheeseSuggestionsBanner(count: Int, onClick: () -> Unit) {
    val roomWord = if (count == 1) "room" else "rooms"
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp)
            .clickable(onClick = onClick),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.secondaryContainer
        )
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("\uD83E\uDDC0", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    "$count $roomWord available from Cheese Tracker",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSecondaryContainer
                )
                Text(
                    "Tap to choose which to add",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSecondaryContainer
                )
            }
            Icon(
                Icons.AutoMirrored.Filled.KeyboardArrowRight,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSecondaryContainer
            )
        }
    }
}

/**
 * The picker behind the banner: tick the rooms to add, or dismiss the lot.
 *
 * Everything starts ticked, so the common case ("yes, these are mine") is one
 * tap, while the room somebody else added the user to can be unticked instead of
 * having to be dealt with after it lands.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CheeseSuggestionsSheet(
    available: List<AvailableCheeseRoom>,
    isImporting: Boolean,
    onAdd: (List<String>) -> Unit,
    onDismissRooms: (List<String>) -> Unit
) {
    val selected = remember(available) {
        mutableStateMapOf<String, Boolean>().apply {
            available.forEach { put(it.cheese_tracker_id, true) }
        }
    }
    val chosen = available.map { it.cheese_tracker_id }.filter { selected[it] == true }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp)
            .navigationBarsPadding()
            .imePadding()
    ) {
        Text("Rooms on Cheese Tracker", style = MaterialTheme.typography.titleLarge)
        Text(
            "These are on your Cheese dashboard but not in the app.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 4.dp, bottom = 12.dp)
        )
        HorizontalDivider()

        available.forEach { room ->
            val isChecked = selected[room.cheese_tracker_id] == true
            ListItem(
                headlineContent = { Text(room.title) },
                supportingContent = { Text(room.room_link ?: "On Cheese Tracker") },
                leadingContent = {
                    Checkbox(
                        checked = isChecked,
                        onCheckedChange = { selected[room.cheese_tracker_id] = it },
                        enabled = !isImporting
                    )
                },
                modifier = Modifier.clickable(enabled = !isImporting) {
                    selected[room.cheese_tracker_id] = !isChecked
                }
            )
        }

        HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.End,
            verticalAlignment = Alignment.CenterVertically
        ) {
            TextButton(
                enabled = !isImporting,
                onClick = { onDismissRooms(available.map { it.cheese_tracker_id }) }
            ) { Text("Not these") }
            Spacer(Modifier.width(8.dp))
            Button(
                enabled = chosen.isNotEmpty() && !isImporting,
                onClick = { onAdd(chosen) }
            ) { Text(if (chosen.size == 1) "Add room" else "Add ${chosen.size} rooms") }
        }
        Spacer(Modifier.height(16.dp))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RoomOptionsSheet(
    room: Room,
    isCheeseConnected: Boolean,
    onDismiss: () -> Unit,
    onViewActivity: (Room) -> Unit,
    onManageSlots: (Room) -> Unit,
    onEdit: (Room) -> Unit,
    onArchive: (Room) -> Unit,
    onDelete: (Room) -> Unit,
    onRevive: (Room) -> Unit,
    onCheeseLinkChange: (Room, Boolean) -> Unit
) {
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp).navigationBarsPadding().imePadding()) {
        Text(room.alias, style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(bottom = 16.dp))
        HorizontalDivider()

        if (room.is_suspended) {
            ListItem(
                headlineContent = { Text("Revive Room") },
                supportingContent = { Text("Resume active status tracking") },
                leadingContent = { Icon(Icons.Default.Link, null, tint = MaterialTheme.colorScheme.tertiary) },
                modifier = Modifier.clickable { onRevive(room) }
            )
        }
        // The two things people actually come here to do, above the fold and above the
        // room-management actions. Tapping the room itself opens its slots, so this is
        // the way to activity -- and the way to slot selection without expanding first.
        ListItem(
            headlineContent = { Text("Room Activity") },
            supportingContent = { Text("Item and check history for this room") },
            leadingContent = { Icon(Icons.AutoMirrored.Filled.List, null, tint = MaterialTheme.colorScheme.primary) },
            modifier = Modifier.clickable { onViewActivity(room) }
        )
        ListItem(
            headlineContent = { Text("Manage Slots") },
            supportingContent = { Text("Choose which slots this room tracks") },
            leadingContent = { Icon(Icons.Default.Tune, null, tint = MaterialTheme.colorScheme.primary) },
            modifier = Modifier.clickable { onManageSlots(room) }
        )
        HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))
        ListItem(
            headlineContent = { Text("Edit Room") },
            supportingContent = { Text("Change the room's name or icon") },
            leadingContent = { Icon(Icons.Default.Edit, null, tint = MaterialTheme.colorScheme.secondary) },
            modifier = Modifier.clickable { onEdit(room) }
        )
        ListItem(
            headlineContent = { Text("Archive Room") },
            supportingContent = { Text("Stop tracking updates but keep history") },
            leadingContent = { Icon(Icons.Default.Inventory2, null, tint = MaterialTheme.colorScheme.secondary) },
            modifier = Modifier.clickable { onArchive(room) }
        )
        // Sharing is per room and reversible either way. Unlinking is local: it
        // leaves the Cheese tracker and any slot claims alone, and never removes
        // the room from the app.
        if (isCheeseConnected) {
            val isLinked = room.cheese_link == "linked"
            ListItem(
                headlineContent = {
                    Text(if (isLinked) "Stop sharing on Cheese" else "Share on Cheese Tracker")
                },
                supportingContent = {
                    Text(
                        when {
                            isLinked && room.cheese_unlisted ->
                                "This room is no longer on your Cheese dashboard"
                            isLinked ->
                                "Stops syncing this room. Your slot claims stay as they are."
                            else ->
                                "Creates this room on Cheese Tracker"
                        }
                    )
                },
                leadingContent = {
                    Icon(
                        if (isLinked) Icons.Default.LinkOff else Icons.Default.Link,
                        null,
                        tint = MaterialTheme.colorScheme.secondary
                    )
                },
                modifier = Modifier.clickable { onCheeseLinkChange(room, !isLinked) }
            )
        }
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
fun AddRoomDialog(
    isAdding: Boolean,
    isCheeseConnected: Boolean,
    defaultSyncToCheese: Boolean,
    onDismiss: () -> Unit,
    /** url, alias, icon, and whether to also create the room on Cheese Tracker. */
    onAdd: (String, String, String, Boolean) -> Unit
) {
    var roomUrl by remember { mutableStateOf("") }
    var alias by remember { mutableStateOf("") }
    var selectedIconName by remember { mutableStateOf("default_icon") }
    var showUrlHelp by remember { mutableStateOf(false) }
    var syncToCheese by remember { mutableStateOf(defaultSyncToCheese) }

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

    // Button is enabled only if URL looks valid, is NOT a socket string, alias is set, and not currently adding
    val canAdd = isValidUrlFormat && !isSocketFormat && alias.isNotBlank() && !isAdding


    AlertDialog(
        onDismissRequest = { if (!isAdding) onDismiss() },
        title = { Text("Add New Room") },
        text = {
            Column {
                TextField(
                    value = roomUrl,
                    onValueChange = { roomUrl = it },
                    label = { Text("Room URL") },
                    placeholder = { Text("archipelago.gg/room/...") },
                    singleLine = true,
                    enabled = !isAdding,
                    // Highlight error state if user enters socket format
                    isError = isSocketFormat,
                    modifier = Modifier.fillMaxWidth(),
                    trailingIcon = {
                        IconButton(onClick = { showUrlHelp = true }, enabled = !isAdding) {
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
                    enabled = !isAdding,
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(Modifier.height(16.dp))
                Text("Select Icon", style = MaterialTheme.typography.labelMedium)
                IconPicker(selected = selectedIconName, onSelect = { if (!isAdding) selectedIconName = it })

                // Publishing creates a real tracker on Cheese Tracker under the
                // user's account, which is not something to do on their behalf
                // without asking. Off means the room stays private to the app.
                if (isCheeseConnected) {
                    Spacer(Modifier.height(16.dp))
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable(enabled = !isAdding) { syncToCheese = !syncToCheese },
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Checkbox(
                            checked = syncToCheese,
                            onCheckedChange = { if (!isAdding) syncToCheese = it },
                            enabled = !isAdding
                        )
                        Spacer(Modifier.width(4.dp))
                        Column {
                            Text(
                                "Also create on Cheese Tracker",
                                style = MaterialTheme.typography.bodyMedium
                            )
                            Text(
                                if (syncToCheese) {
                                    "Takes a minute or two to appear there."
                                } else {
                                    "This room stays in the app only."
                                },
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }

                if (isAdding) {
                    Spacer(Modifier.height(16.dp))
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        CircularProgressIndicator(modifier = Modifier.size(24.dp))
                        Spacer(modifier = Modifier.width(12.dp))
                        Text(
                            text = "Verifying Archipelago room...",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                enabled = canAdd,
                onClick = { onAdd(roomUrl, alias, selectedIconName, syncToCheese) }
            ) { Text("Add") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !isAdding) { Text("Cancel") }
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

/**
 * Renaming and re-iconing a room. Nothing else.
 *
 * Slot selection used to hang off the bottom of this dialog, which is how it ended up
 * three taps from anywhere and inside a form that has nothing to do with it. It now lives
 * on the room card and in the room's overflow sheet.
 */
@Composable
fun EditRoomDialog(
    room: Room,
    onDismiss: () -> Unit,
    onConfirm: (String, String) -> Unit
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