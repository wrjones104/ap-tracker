package com.jones.aptracker.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import android.widget.Toast
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.filled.NotificationsPaused
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.accompanist.swiperefresh.SwipeRefresh
import com.google.accompanist.swiperefresh.rememberSwipeRefreshState
import com.jones.aptracker.network.HintEntity
import com.jones.aptracker.network.HistoryItem
import com.jones.aptracker.network.IgnoreItem
import com.jones.aptracker.ui.theme.APTheme
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

// --- 1. THE WRAPPER ---
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryScreen(
    roomId: Int?,
    roomAlias: String?,
    historyViewModel: HistoryViewModel = viewModel(),
    userViewModel: UserViewModel = viewModel(),
    onBackClick: () -> Unit
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(roomAlias ?: "History") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        HistoryContent(
            roomId = roomId,
            historyViewModel = historyViewModel,
            userViewModel = userViewModel,
            modifier = Modifier.padding(padding)
        )
    }
}

// --- 2. THE REUSABLE CONTENT ---
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun HistoryContent(
    roomId: Int?,
    historyViewModel: HistoryViewModel,
    userViewModel: UserViewModel,
    modifier: Modifier = Modifier
) {
    LaunchedEffect(key1 = roomId) {
        historyViewModel.loadHistoryFor(roomId)
    }

    val isLoading by historyViewModel.isLoading.collectAsState()
    val errorMessage by historyViewModel.errorMessage
    val actionMessage by historyViewModel.actionMessage.collectAsState()
    val searchQuery by historyViewModel.searchQuery

    // Filter States
    val showFoundHints by historyViewModel.showFoundHints.collectAsState()
    val showFinished by historyViewModel.showFinished.collectAsState()
    val useCondensed by historyViewModel.useCondensed.collectAsState()

    // New Type Filter States (Traps Removed)
    val showProgression by historyViewModel.showProgression.collectAsState()
    val showUseful by historyViewModel.showUseful.collectAsState()

    // Ignored Items filter
    val showIgnoredItems by historyViewModel.showIgnoredItems.collectAsState()
    val ignoreList by userViewModel.ignoreList.collectAsState()

    val roomNames by historyViewModel.roomNames.collectAsState()

    var selectedItem by remember { mutableStateOf<HistoryItem?>(null) }
    var selectedHint by remember { mutableStateOf<HintEntity?>(null) }
    var showFilterSheet by remember { mutableStateOf(false) }
    var showSnoozeDialogForSlot by remember { mutableStateOf<Pair<Int, Int>?>(null) }

    val context = LocalContext.current
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val pagerState = rememberPagerState(pageCount = { 2 })
    val coroutineScope = rememberCoroutineScope()
    val snackbarHostState = remember { SnackbarHostState() }

    // Error Handling
    LaunchedEffect(actionMessage) {
        actionMessage?.let {
            snackbarHostState.showSnackbar(it)
            historyViewModel.clearActionMessage()
        }
    }
    LaunchedEffect(errorMessage) {
        errorMessage?.let {
            snackbarHostState.showSnackbar(it, duration = SnackbarDuration.Short)
            historyViewModel.clearErrorMessage()
        }
    }

    Box(modifier = modifier.fillMaxSize()) {
        val swipeRefreshState = rememberSwipeRefreshState(isRefreshing = isLoading)

        SwipeRefresh(
            state = swipeRefreshState,
            onRefresh = { historyViewModel.refreshAllHistory() },
            modifier = Modifier.fillMaxSize()
        ) {
            Column(modifier = Modifier.fillMaxSize()) {

                // --- SEARCH & FILTER ROW ---
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    TextField(
                        value = searchQuery,
                        onValueChange = { historyViewModel.onSearchQueryChanged(it) },
                        label = { Text("Search") },
                        leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                        modifier = Modifier
                            .weight(1f)
                            .padding(end = 8.dp),
                        singleLine = true
                    )
                    // The Filter Button
                    FilledTonalIconButton(onClick = { showFilterSheet = true }) {
                        Icon(Icons.Default.Tune, contentDescription = "View Options")
                    }
                }

                // --- TABS ---
                TabRow(selectedTabIndex = pagerState.currentPage) {
                    listOf("Items", "Hints").forEachIndexed { index, title ->
                        Tab(
                            selected = pagerState.currentPage == index,
                            onClick = { coroutineScope.launch { pagerState.animateScrollToPage(index) } },
                            text = { Text(title) }
                        )
                    }
                }

                // --- PAGER CONTENT ---
                HorizontalPager(
                    state = pagerState,
                    modifier = Modifier.weight(1f)
                ) { page ->
                    // Determine if we should show the filter chip.
                    // If a roomId was passed (e.g. from Main Screen), we are locked to that room, so hide the filter.
                    val showRoomFilter = roomId == null

                    when (page) {
                        0 -> ItemHistoryTab(
                            historyViewModel = historyViewModel,
                            searchQuery = searchQuery,
                            onItemClick = { selectedItem = it },
                            showRoomFilter = showRoomFilter,
                            showIgnoredItems = showIgnoredItems,
                            ignoreList = ignoreList
                        )
                        1 -> HintHistoryTab(
                            historyViewModel = historyViewModel,
                            searchQuery = searchQuery,
                            onHintClick = { selectedHint = it },
                            showRoomFilter = showRoomFilter,
                            showIgnoredItems = showIgnoredItems,
                            ignoreList = ignoreList
                        )
                    }
                }
            }
        }

        SnackbarHost(
            hostState = snackbarHostState,
            modifier = Modifier.align(Alignment.BottomCenter)
        )
    }

    if (showFilterSheet) {
        ModalBottomSheet(
            onDismissRequest = { showFilterSheet = false },
            sheetState = sheetState
        ) {
            HistoryFilterSheet(
                showFinished = showFinished,
                onShowFinishedChange = { historyViewModel.setShowFinished(it) },
                showFoundHints = showFoundHints,
                onShowFoundHintsChange = { historyViewModel.setShowFoundHints(it) },
                useCondensed = useCondensed,
                onUseCondensedChange = { historyViewModel.setUseCondensed(it) },
                // NEW (Traps Removed)
                showProgression = showProgression,
                onShowProgressionChange = { historyViewModel.setShowProgression(it) },
                showUseful = showUseful,
                onShowUsefulChange = { historyViewModel.setShowUseful(it) },
                // ---
                showIgnoredItems = showIgnoredItems,
                onShowIgnoredItemsChange = { historyViewModel.setShowIgnoredItems(it) },
                isHintTabSelected = pagerState.currentPage == 1,
                onDismiss = { showFilterSheet = false }
            )
        }
    }

    showSnoozeDialogForSlot?.let { (snoozeRoomId, snoozeSlotId) ->
        SnoozeDialog(
            title = "Snooze Player",
            currentSnoozeUntil = null,
            activeSnoozeDetails = emptyList(), // Pass empty list if not using details here
            onDismiss = { showSnoozeDialogForSlot = null },
            onSnoozeSelected = { minutes ->
                userViewModel.setSlotSnooze(snoozeRoomId, snoozeSlotId, minutes)
                showSnoozeDialogForSlot = null
            }
        )
    }

    // --- DETAIL SHEETS ---
    if (selectedItem != null) {
        val itemRoomName = selectedItem!!.db_id?.let { roomNames[it] } ?: "Unknown Room"

        ModalBottomSheet(onDismissRequest = { selectedItem = null }, sheetState = sheetState) {
            HistoryDetailSheet(
                item = selectedItem!!,
                roomName = itemRoomName,
                onOpenTracker = {
                    val cleanHost = (selectedItem!!.host?.takeIf { it.isNotBlank() } ?: "archipelago.gg")
                        .removePrefix("https://").removePrefix("http://")
                    val url = "https://${cleanHost}/tracker/${selectedItem!!.tracker_id}/0/${selectedItem!!.slot_id}"
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                    selectedItem = null
                },
                onIgnoreItem = { game ->
                    historyViewModel.ignoreItem(selectedItem!!.itemName, game)
                    selectedItem = null
                },
                onSnoozePlayer = {
                    // Only trigger if we have valid IDs
                    selectedItem?.let { item ->
                        val dbId = item.db_id
                        val slotId = item.slot_id
                        if (dbId != null && slotId != null) {
                            showSnoozeDialogForSlot = dbId to slotId
                            selectedItem = null // Close sheet
                        }
                    }
                }
            )
        }
    }

    if (selectedHint != null) {
        ModalBottomSheet(onDismissRequest = { selectedHint = null }, sheetState = sheetState) {
            HintDetailSheet(hint = selectedHint!!, onDismiss = { selectedHint = null })
        }
    }
}

@Composable
fun HistoryFilterSheet(
    showFinished: Boolean,
    onShowFinishedChange: (Boolean) -> Unit,
    showFoundHints: Boolean,
    onShowFoundHintsChange: (Boolean) -> Unit,
    useCondensed: Boolean,
    onUseCondensedChange: (Boolean) -> Unit,
    showProgression: Boolean,
    onShowProgressionChange: (Boolean) -> Unit,
    showUseful: Boolean,
    onShowUsefulChange: (Boolean) -> Unit,
    showIgnoredItems: Boolean,
    onShowIgnoredItemsChange: (Boolean) -> Unit,

    isHintTabSelected: Boolean,
    onDismiss: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp)
            .navigationBarsPadding()
    ) {
        Text(
            text = "View Options",
            style = MaterialTheme.typography.titleLarge,
            modifier = Modifier.padding(bottom = 16.dp)
        )

        // --- NEW: Item Types Section ---
        Text(
            text = "Item Types",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(bottom = 8.dp),
            color = MaterialTheme.colorScheme.primary
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            FilterChip(
                selected = showProgression,
                onClick = { onShowProgressionChange(!showProgression) },
                label = { Text("Progression") },
                leadingIcon = if (showProgression) {
                    { Icon(Icons.Default.Check, null) }
                } else null
            )
            FilterChip(
                selected = showUseful,
                onClick = { onShowUsefulChange(!showUseful) },
                label = { Text("Useful") },
                leadingIcon = if (showUseful) {
                    { Icon(Icons.Default.Check, null) }
                } else null
            )
        }

        HorizontalDivider(modifier = Modifier.padding(vertical = 16.dp))

        // Toggle 1: Show Original Slot Name
        val showOriginalNames = !useCondensed

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { onUseCondensedChange(!useCondensed) }
                .padding(vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "Show Original Slot Name",
                    style = MaterialTheme.typography.bodyLarge
                )
                Text(
                    text = if (showOriginalNames) "Showing 'Alias (Original Slot Name)'" else "Showing Alias only",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Switch(
                checked = showOriginalNames,
                onCheckedChange = { isChecked -> onUseCondensedChange(!isChecked) },
                modifier = Modifier.padding(start = 16.dp)
            )
        }

        HorizontalDivider()

        // Toggle 2: Finished Slots
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { onShowFinishedChange(!showFinished) }
                .padding(vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "Show Finished Slots",
                    style = MaterialTheme.typography.bodyLarge
                )
                Text(
                    text = "Include items/hints for players who have already completed their goal.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Switch(
                checked = showFinished,
                onCheckedChange = onShowFinishedChange,
                modifier = Modifier.padding(start = 16.dp)
            )
        }

        // Toggle 3: Found Hints (Conditional)
        AnimatedVisibility(visible = isHintTabSelected) {
            Column {
                HorizontalDivider()
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onShowFoundHintsChange(!showFoundHints) }
                        .padding(vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = "Show Found Hints",
                            style = MaterialTheme.typography.bodyLarge
                        )
                        Text(
                            text = "Include hints for items that have already been found.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    Switch(
                        checked = showFoundHints,
                        onCheckedChange = onShowFoundHintsChange,
                        modifier = Modifier.padding(start = 16.dp)
                    )
                }
            }
        }

        HorizontalDivider()

        // Toggle 4: Ignored Items
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { onShowIgnoredItemsChange(!showIgnoredItems) }
                .padding(vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "Show Ignored Items",
                    style = MaterialTheme.typography.bodyLarge
                )
                Text(
                    text = "Include items/hints that match your ignore list.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Switch(
                checked = showIgnoredItems,
                onCheckedChange = onShowIgnoredItemsChange,
                modifier = Modifier.padding(start = 16.dp)
            )
        }

        Spacer(Modifier.height(24.dp))

        Button(
            onClick = onDismiss,
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Done")
        }
    }
}

@Composable
fun HistoryDetailSheet(
    item: HistoryItem,
    roomName: String,
    onOpenTracker: () -> Unit,
    onIgnoreItem: (String?) -> Unit,
    onSnoozePlayer: () -> Unit
) {
    val formatter = remember {
        DateTimeFormatter.ofLocalizedDateTime(FormatStyle.MEDIUM)
            .withZone(ZoneId.systemDefault())
    }

    fun formatName(name: String, alias: String?): String {
        return if (alias.isNullOrBlank()) name else "$alias ($name)"
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 24.dp, end = 24.dp, top = 24.dp, bottom = 48.dp)
            .navigationBarsPadding()
    ) {
        // --- Header ---
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                imageVector = getIconByName(item.icon_name),
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(40.dp)
            )
            Spacer(Modifier.width(16.dp))
            Column {
                Text(
                    text = item.itemName,
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = formatTimestamp(item.timestamp, formatter),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }

        HorizontalDivider(modifier = Modifier.padding(vertical = 16.dp))

        // --- Compact Data Grid (2 Columns) ---
        Row(modifier = Modifier.fillMaxWidth()) {
            // LEFT COLUMN
            Column(modifier = Modifier.weight(1f)) {
                CompactDetailItem(
                    label = "Room",
                    value = roomName
                )
                Spacer(Modifier.height(12.dp))
                CompactDetailItem(
                    label = "Sender",
                    value = if (item.senderName != null && item.senderName != item.playerName) {
                        formatName(item.senderName, item.senderAlias)
                    } else {
                        "Server / Self"
                    }
                )
            }

            Spacer(Modifier.width(16.dp))

            // RIGHT COLUMN
            Column(modifier = Modifier.weight(1f)) {
                if (!item.receivingGame.isNullOrBlank()) {
                    CompactDetailItem(
                        label = "Game",
                        value = item.receivingGame
                    )
                    Spacer(Modifier.height(12.dp))
                }
                CompactDetailItem(
                    label = "Receiver",
                    value = formatName(item.playerName, item.playerAlias)
                )
            }
        }

        Spacer(Modifier.height(24.dp))

        // --- Actions ---
        Button(
            onClick = onOpenTracker,
            modifier = Modifier.fillMaxWidth()
        ) {
            Icon(Icons.Default.OpenInNew, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text("Open in Web Tracker")
        }

        Spacer(Modifier.height(8.dp))

        if (item.slot_id != null && item.db_id != null) {
            OutlinedButton(
                onClick = onSnoozePlayer,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.secondary)
            ) {
                Icon(Icons.Default.NotificationsPaused, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Text("Snooze Player")
            }
            Spacer(Modifier.height(8.dp))
        }

        // Ignore Actions
        if (!item.receivingGame.isNullOrBlank()) {
            OutlinedButton(
                onClick = { onIgnoreItem(item.receivingGame) },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error)
            ) {
                Icon(Icons.Default.VisibilityOff, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Text("Ignore in ${item.receivingGame}")
            }
            Spacer(Modifier.height(8.dp))
        }

        OutlinedButton(
            onClick = { onIgnoreItem(null) },
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error)
        ) {
            Icon(Icons.Default.VisibilityOff, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text("Ignore Globally")
        }
    }
}

@Composable
fun CompactDetailItem(label: String, value: String) {
    Column {
        Text(
            text = label.uppercase(),
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


@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ItemHistoryTab(
    historyViewModel: HistoryViewModel,
    searchQuery: String,
    onItemClick: (HistoryItem) -> Unit,
    showRoomFilter: Boolean,
    showIgnoredItems: Boolean,
    ignoreList: List<IgnoreItem>
) {
    val fullHistory by historyViewModel.itemHistory.collectAsState()
    val availablePlayers by historyViewModel.availablePlayers.collectAsState()
    val selectedPlayer by historyViewModel.selectedPlayerFilter.collectAsState()
    val showFinished by historyViewModel.showFinished.collectAsState()
    val finishedKeys by historyViewModel.finishedPlayerKeys.collectAsState()
    val useCondensed by historyViewModel.useCondensed.collectAsState()

    // Type Filters (Traps Removed)
    val showProgression by historyViewModel.showProgression.collectAsState()
    val showUseful by historyViewModel.showUseful.collectAsState()

    val historyFilter by historyViewModel.historyFilter.collectAsState()
    val activeRoomIds by historyViewModel.activeRoomIds.collectAsState()
    val archivedRoomIds by historyViewModel.archivedRoomIds.collectAsState()
    val availableRooms by historyViewModel.availableRooms.collectAsState()

    val formatter = remember {
        DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT)
            .withZone(ZoneId.systemDefault())
    }

    val isDark = isSystemInDarkTheme()
    val finishedColor = if (isDark) Color(0xFF81C784) else Color(0xFF0E8A0E)

    // Filter Logic
    val itemsToShow = remember(
        fullHistory, searchQuery, selectedPlayer, showFinished, finishedKeys, historyFilter,
        activeRoomIds, archivedRoomIds, showProgression, showUseful, showIgnoredItems, ignoreList
    ) {
        fullHistory.filter { item ->
            val matchesSearch = searchQuery.isBlank() ||
                    item.playerName.contains(searchQuery, ignoreCase = true) ||
                    item.itemName.contains(searchQuery, ignoreCase = true)

            val matchesRoom = when (val f = historyFilter) {
                is HistoryFilter.Active -> item.db_id in activeRoomIds
                is HistoryFilter.Archived -> item.db_id in archivedRoomIds
                is HistoryFilter.All -> true
                is HistoryFilter.Specific -> item.db_id == f.roomId
            }

            val matchesPlayer = selectedPlayer == null || item.playerName == selectedPlayer

            val isFinished = if (item.db_id != null) {
                finishedKeys.contains(item.db_id to item.playerName)
            } else {
                false
            }
            val matchesFinished = showFinished || !isFinished

            // --- TYPE CHECK (Prioritized to match visual colors) ---
            val isProgression = (item.itemFlags and 1) != 0
            val isUseful = (item.itemFlags and 2) != 0

            val matchesType = if (isProgression) {
                showProgression
            } else if (isUseful) {
                showUseful
            } else {
                // Determine behavior for items that are NEITHER (e.g. traps/junk)
                // Since we don't have a toggle for them, we hide them if they don't match above.
                // This corresponds to "false" in the old logic when toggles were off.
                false
            }

            val isIgnored = ignoreList.any { ignoreRule ->
                ignoreRule.itemName.equals(item.itemName, ignoreCase = true) &&
                        (ignoreRule.gameName.isNullOrBlank() || ignoreRule.gameName.equals(item.receivingGame, ignoreCase = true))
            }
            val matchesIgnored = showIgnoredItems || !isIgnored

            matchesSearch && matchesRoom && matchesPlayer && matchesFinished && matchesType && matchesIgnored
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // 1. Room Filter
            if (showRoomFilter) {
                RoomFilterChip(
                    currentFilter = historyFilter,
                    availableRooms = availableRooms,
                    onFilterSelected = { historyViewModel.setHistoryFilter(it) }
                )
                Spacer(modifier = Modifier.width(8.dp))

                Box(
                    modifier = Modifier
                        .height(32.dp)
                        .width(1.dp)
                        .padding(vertical = 4.dp)
                        .background(MaterialTheme.colorScheme.outlineVariant)
                )
                Spacer(modifier = Modifier.width(8.dp))
            }

            // 2. Slot Chips
            if (availablePlayers.isNotEmpty()) {
                LazyRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.weight(1f)
                ) {
                    item {
                        FilterChip(
                            selected = selectedPlayer == null,
                            onClick = { historyViewModel.onPlayerFilterSelected(null) },
                            label = { Text("All Slots") },
                            colors = FilterChipDefaults.filterChipColors(
                                selectedContainerColor = MaterialTheme.colorScheme.primaryContainer,
                                selectedLabelColor = MaterialTheme.colorScheme.onPrimaryContainer
                            )
                        )
                    }
                    items(availablePlayers) { playerInfo ->
                        FilterChip(
                            selected = playerInfo.originalName == selectedPlayer,
                            onClick = { historyViewModel.onPlayerFilterSelected(playerInfo.originalName) },
                            label = {
                                Text(getDisplayName(playerInfo.originalName, playerInfo.alias, useCondensed))
                            },
                            colors = FilterChipDefaults.filterChipColors(
                                selectedContainerColor = MaterialTheme.colorScheme.primaryContainer,
                                selectedLabelColor = MaterialTheme.colorScheme.onPrimaryContainer
                            )
                        )
                    }
                }
            }
        }

        if (itemsToShow.isEmpty() && !historyViewModel.isLoading.collectAsState().value) {
            Box(modifier = Modifier.fillMaxSize().weight(1f), contentAlignment = Alignment.Center) {
                Text("No item history matches.")
            }
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(itemsToShow, key = { it.id }) { item ->
                    val isClickable = item.tracker_id != null && item.slot_id != null
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable(enabled = isClickable) {
                                if (isClickable) {
                                    onItemClick(item)
                                }
                            },
                        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
                    ) {
                        Row(
                            modifier = Modifier.padding(16.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(
                                imageVector = getIconByName(item.icon_name),
                                contentDescription = "Item received",
                                tint = MaterialTheme.colorScheme.primary
                            )
                            Spacer(modifier = Modifier.width(16.dp))
                            Column(modifier = Modifier.weight(1f)) {

                                val itemColor = when {
                                    (item.itemFlags and 1) != 0 -> APTheme.colors.progression
                                    (item.itemFlags and 2) != 0 -> APTheme.colors.useful
                                    (item.itemFlags and 4) != 0 -> APTheme.colors.trap
                                    else -> Color.Unspecified
                                }

                                val displayPlayer = getDisplayName(item.playerName, item.playerAlias, useCondensed)
                                val displaySender = getDisplayName(item.senderName, item.senderAlias, useCondensed)

                                // MAIN TEXT: "Player received Item"
                                Text(
                                    buildAnnotatedString {
                                        if (item.isPlayerFinished) {
                                            withStyle(style = SpanStyle(color = finishedColor, fontWeight = FontWeight.SemiBold)) {
                                                append("🏁 $displayPlayer ")
                                            }
                                        } else {
                                            withStyle(style = SpanStyle(fontWeight = FontWeight.SemiBold)) {
                                                append("$displayPlayer ")
                                            }
                                        }

                                        append("received ")

                                        withStyle(style = SpanStyle(color = itemColor, fontWeight = FontWeight.Bold)) {
                                            append(item.itemName)
                                        }
                                    },
                                    style = MaterialTheme.typography.bodyLarge
                                )

                                // SUBTEXT: "Sent by Sender • Time"
                                val subtext = buildString {
                                    if (!item.senderName.isNullOrBlank() && item.senderName != item.playerName) {
                                        append("Sent by $displaySender • ")
                                    }
                                    append(formatTimestamp(item.timestamp, formatter))
                                }

                                Text(
                                    text = subtext,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = Color.Gray
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun RoomFilterChip(
    currentFilter: HistoryFilter,
    availableRooms: List<Pair<Int, String>>,
    onFilterSelected: (HistoryFilter) -> Unit
) {
    var expanded by remember { mutableStateOf(false) }

    val label = when (currentFilter) {
        HistoryFilter.Active -> "Active Rooms"
        HistoryFilter.Archived -> "Archived Rooms"
        HistoryFilter.All -> "All History"
        is HistoryFilter.Specific -> availableRooms.find { it.first == currentFilter.roomId }?.second ?: "Unknown Room"
    }

    val isMetaFilter = currentFilter !is HistoryFilter.Specific

    Box {
        FilterChip(
            selected = true,
            onClick = { expanded = true },
            label = {
                Text(
                    text = label,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.widthIn(max = 160.dp)
                )
            },
            trailingIcon = {
                Icon(
                    imageVector = Icons.Default.KeyboardArrowDown,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp)
                )
            },
            colors = FilterChipDefaults.filterChipColors(
                containerColor = if (isMetaFilter) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.secondaryContainer,
                labelColor = if (isMetaFilter) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSecondaryContainer
            )
        )

        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false }
        ) {
            DropdownMenuItem(
                text = { Text("Active Rooms") },
                onClick = { onFilterSelected(HistoryFilter.Active); expanded = false },
                trailingIcon = { if (currentFilter is HistoryFilter.Active) Icon(Icons.Default.Check, null) }
            )
            DropdownMenuItem(
                text = { Text("Archived Rooms") },
                onClick = { onFilterSelected(HistoryFilter.Archived); expanded = false },
                trailingIcon = { if (currentFilter is HistoryFilter.Archived) Icon(Icons.Default.Check, null) }
            )
            DropdownMenuItem(
                text = { Text("All History") },
                onClick = { onFilterSelected(HistoryFilter.All); expanded = false },
                trailingIcon = { if (currentFilter is HistoryFilter.All) Icon(Icons.Default.Check, null) }
            )

            if (availableRooms.isNotEmpty()) {
                HorizontalDivider()
                availableRooms.forEach { (id, name) ->
                    DropdownMenuItem(
                        text = { Text(name) },
                        onClick = {
                            onFilterSelected(HistoryFilter.Specific(id))
                            expanded = false
                        },
                        trailingIcon = {
                            if (currentFilter is HistoryFilter.Specific && currentFilter.roomId == id) {
                                Icon(Icons.Default.Check, null)
                            }
                        }
                    )
                }
            }
        }
    }
}


@Composable
fun HintHistoryTab(
    historyViewModel: HistoryViewModel,
    searchQuery: String,
    onHintClick: (HintEntity) -> Unit,
    showRoomFilter: Boolean,
    showIgnoredItems: Boolean,
    ignoreList: List<IgnoreItem>
) {
    val hintsForYou by historyViewModel.hintsForYou.collectAsState()
    val hintsByYou by historyViewModel.hintsByYou.collectAsState()
    val useCondensed by historyViewModel.useCondensed.collectAsState()
    val showFinished by historyViewModel.showFinished.collectAsState()
    val finishedKeys by historyViewModel.finishedPlayerKeys.collectAsState()

    // Type Filters
    val showProgression by historyViewModel.showProgression.collectAsState()
    val showUseful by historyViewModel.showUseful.collectAsState()

    val availablePlayers by historyViewModel.availableHintPlayers.collectAsState()
    val selectedPlayer by historyViewModel.selectedPlayerFilter.collectAsState()

    val historyFilter by historyViewModel.historyFilter.collectAsState()
    val activeRoomIds by historyViewModel.activeRoomIds.collectAsState()
    val archivedRoomIds by historyViewModel.archivedRoomIds.collectAsState()
    val availableRooms by historyViewModel.availableRooms.collectAsState()

    val formatter = remember {
        DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT)
            .withZone(ZoneId.systemDefault())
    }

    var isForYouExpanded by rememberSaveable { mutableStateOf(true) }
    var isByYouExpanded by rememberSaveable { mutableStateOf(true) }

    val filteredHintsForYou = remember(
        hintsForYou, searchQuery, showFinished, finishedKeys, selectedPlayer,
        historyFilter, activeRoomIds, archivedRoomIds,
        showProgression, showUseful, showIgnoredItems, ignoreList
    ) {
        filterHints(
            hintsForYou, searchQuery, showFinished, finishedKeys, selectedPlayer,
            historyFilter, activeRoomIds, archivedRoomIds,
            showProgression, showUseful, showIgnoredItems, ignoreList
        )
    }
    val filteredHintsByYou = remember(
        hintsByYou, searchQuery, showFinished, finishedKeys, selectedPlayer,
        historyFilter, activeRoomIds, archivedRoomIds,
        showProgression, showUseful, showIgnoredItems, ignoreList
    ) {
        filterHints(
            hintsByYou, searchQuery, showFinished, finishedKeys, selectedPlayer,
            historyFilter, activeRoomIds, archivedRoomIds,
            showProgression, showUseful, showIgnoredItems, ignoreList
        )
    }

    Column(modifier = Modifier.fillMaxSize()) {

        // Filter Row (Room Chip + Player Chips) ---
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // 1. Room Filter
            if (showRoomFilter) {
                RoomFilterChip(
                    currentFilter = historyFilter,
                    availableRooms = availableRooms,
                    onFilterSelected = { historyViewModel.setHistoryFilter(it) }
                )
                Spacer(modifier = Modifier.width(8.dp))

                Box(
                    modifier = Modifier
                        .height(32.dp)
                        .width(1.dp)
                        .padding(vertical = 4.dp)
                        .background(MaterialTheme.colorScheme.outlineVariant)
                )
                Spacer(modifier = Modifier.width(8.dp))
            }

            // 2. Player Chips
            if (availablePlayers.isNotEmpty()) {
                LazyRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.weight(1f)
                ) {
                    item {
                        FilterChip(
                            selected = selectedPlayer == null,
                            onClick = { historyViewModel.onPlayerFilterSelected(null) },
                            label = { Text("All") },
                            colors = FilterChipDefaults.filterChipColors(
                                selectedContainerColor = MaterialTheme.colorScheme.primaryContainer,
                                selectedLabelColor = MaterialTheme.colorScheme.onPrimaryContainer
                            )
                        )
                    }
                    items(availablePlayers) { playerInfo ->
                        FilterChip(
                            selected = playerInfo.originalName == selectedPlayer,
                            onClick = { historyViewModel.onPlayerFilterSelected(playerInfo.originalName) },
                            label = {
                                Text(getDisplayName(playerInfo.originalName, playerInfo.alias, useCondensed))
                            },
                            colors = FilterChipDefaults.filterChipColors(
                                selectedContainerColor = MaterialTheme.colorScheme.primaryContainer,
                                selectedLabelColor = MaterialTheme.colorScheme.onPrimaryContainer
                            )
                        )
                    }
                }
            }
        }

        if (filteredHintsForYou.isEmpty() && filteredHintsByYou.isEmpty() && !historyViewModel.isLoading.collectAsState().value) {
            Box(modifier = Modifier.fillMaxSize().weight(1f), contentAlignment = Alignment.Center) {
                Text("No hint history found.")
            }
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                if (filteredHintsForYou.isNotEmpty()) {
                    item {
                        SectionHeader(
                            title = "Hints For Your Items",
                            count = filteredHintsForYou.size,
                            isExpanded = isForYouExpanded,
                            onClick = { isForYouExpanded = !isForYouExpanded }
                        )
                    }
                    if (isForYouExpanded) {
                        items(filteredHintsForYou, key = { it.hint_db_id }) { hint ->
                            HintCard(
                                hint = hint,
                                formatter = formatter,
                                useCondensed = useCondensed,
                                onClick = { onHintClick(hint) }
                            )
                        }
                    }
                }

                if (filteredHintsByYou.isNotEmpty()) {
                    item {
                        if (filteredHintsForYou.isNotEmpty()) {
                            Spacer(Modifier.height(16.dp))
                            HorizontalDivider() // Updated Divider
                            Spacer(Modifier.height(16.dp))
                        }
                        SectionHeader(
                            title = "Hints For Items In Your World",
                            count = filteredHintsByYou.size,
                            isExpanded = isByYouExpanded,
                            onClick = { isByYouExpanded = !isByYouExpanded }
                        )
                    }
                    if (isByYouExpanded) {
                        items(filteredHintsByYou, key = { it.hint_db_id }) { hint ->
                            HintCard(
                                hint = hint,
                                formatter = formatter,
                                useCondensed = useCondensed,
                                onClick = { onHintClick(hint) }
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun HintCard(
    hint: HintEntity,
    formatter: DateTimeFormatter,
    useCondensed: Boolean,
    onClick: () -> Unit
) {
    val cardColors = if (hint.isFound) {
        CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.secondaryContainer,
            contentColor = MaterialTheme.colorScheme.onSecondaryContainer
        )
    } else {
        CardDefaults.cardColors()
    }

    val iconTint = if (hint.isFound) {
        MaterialTheme.colorScheme.onSecondaryContainer
    } else {
        MaterialTheme.colorScheme.primary
    }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
        colors = cardColors
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = if (hint.isFound) Icons.Default.CheckCircle else Icons.Default.Info,
                contentDescription = if (hint.isFound) "Found" else "Hint",
                tint = iconTint,
                modifier = Modifier.size(24.dp)
            )

            Spacer(modifier = Modifier.width(16.dp))

            Column(modifier = Modifier.weight(1f)) {
                val itemColor = when {
                    (hint.itemFlags and 1) != 0 -> APTheme.colors.progression
                    (hint.itemFlags and 2) != 0 -> APTheme.colors.useful
                    (hint.itemFlags and 4) != 0 -> APTheme.colors.trap
                    else -> Color.Unspecified
                }

                val itemOwner = getDisplayName(hint.itemOwnerName, hint.itemOwnerAlias, useCondensed)
                val locOwner = getDisplayName(hint.locationOwnerName, hint.locationOwnerAlias, useCondensed)

                // Line 1: [ItemOwner]'s [Item]
                Text(
                    buildAnnotatedString {
                        withStyle(style = SpanStyle(fontWeight = FontWeight.SemiBold)) {
                            append("$itemOwner's ")
                        }
                        withStyle(style = SpanStyle(color = itemColor, fontWeight = FontWeight.Bold)) {
                            append(hint.itemName)
                        }
                    },
                    style = MaterialTheme.typography.bodyLarge
                )

                // Line 2: is at [Location]
                Text(
                    text = "is at ${hint.locationName}",
                    style = MaterialTheme.typography.bodyMedium
                )

                // Line 3: in [LocationOwner]'s World • Timestamp
                Text(
                    text = buildAnnotatedString {
                        append("in ")
                        withStyle(style = SpanStyle(fontWeight = FontWeight.Medium)) {
                            append("$locOwner's World")
                        }

                        append(" • ")

                        if (hint.isFound) {
                            withStyle(style = SpanStyle(fontWeight = FontWeight.Bold)) {
                                append("Found")
                            }
                            append(" • ")
                        }
                        append(formatTimestamp(hint.timestamp, formatter))
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = LocalContentColor.current.copy(alpha = 0.7f)
                )
            }
        }
    }
}

@Composable
fun HintDetailSheet(
    hint: HintEntity,
    onDismiss: () -> Unit
) {
    val context = LocalContext.current

    // Explicit copy text: [ItemOwner]'s [Item] is at [Location] in [LocationOwner]'s World
    val itemOwner = getDisplayName(hint.itemOwnerName, hint.itemOwnerAlias, useCondensed = false)
    val locOwner = getDisplayName(hint.locationOwnerName, hint.locationOwnerAlias, useCondensed = false)
    val copyText = "$itemOwner's ${hint.itemName} is at ${hint.locationName} in $locOwner's World"

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(24.dp)
            .navigationBarsPadding()
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                imageVector = Icons.Default.Info,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.secondary,
                modifier = Modifier.size(32.dp)
            )
            Spacer(Modifier.width(16.dp))
            Text(
                text = "Hint Detail",
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold
            )
        }

        Spacer(Modifier.height(16.dp))

        Card(
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
            modifier = Modifier.fillMaxWidth()
        ) {
            Text(
                text = copyText,
                style = MaterialTheme.typography.bodyLarge,
                modifier = Modifier.padding(16.dp)
            )
        }

        Spacer(Modifier.height(24.dp))

        Button(
            onClick = {
                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                val clip = ClipData.newPlainText("Archipelago Hint", copyText)
                clipboard.setPrimaryClip(clip)
                Toast.makeText(context, "Copied to clipboard", Toast.LENGTH_SHORT).show()
                onDismiss()
            },
            modifier = Modifier.fillMaxWidth()
        ) {
            Icon(Icons.Default.ContentCopy, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text("Copy Text to Clipboard")
        }
    }
}

private fun filterHints(
    hints: List<HintEntity>,
    query: String,
    showFinished: Boolean,
    finishedKeys: Set<Pair<Int, String>>,
    selectedPlayer: String?,
    historyFilter: HistoryFilter,
    activeRoomIds: Set<Int>,
    archivedRoomIds: Set<Int>,
    showProgression: Boolean,
    showUseful: Boolean,
    showIgnoredItems: Boolean,
    ignoreList: List<IgnoreItem>
): List<HintEntity> {
    return hints.filter { hint ->
        // 1. Room Check
        val matchesRoom = when (val f = historyFilter) {
            is HistoryFilter.Active -> hint.roomDbId in activeRoomIds
            is HistoryFilter.Archived -> hint.roomDbId in archivedRoomIds
            is HistoryFilter.All -> true
            is HistoryFilter.Specific -> hint.roomDbId == f.roomId
        }

        val matchesQuery = if (query.isBlank()) true else {
            hint.itemName.contains(query, ignoreCase = true) ||
                    hint.locationName.contains(query, ignoreCase = true) ||
                    hint.itemOwnerName.contains(query, ignoreCase = true) ||
                    hint.locationOwnerName.contains(query, ignoreCase = true) ||
                    hint.roomAlias.contains(query, ignoreCase = true)
        }

        val isItemOwnerFinished = finishedKeys.contains(hint.roomDbId to hint.itemOwnerName)
        val matchesFinished = showFinished || !isItemOwnerFinished

        val matchesPlayer = if (selectedPlayer == null) true else {
            if (hint.hintType == "for_you") {
                hint.itemOwnerName == selectedPlayer
            } else {
                hint.locationOwnerName == selectedPlayer
            }
        }

        // --- TYPE CHECK (Prioritized to match visual colors) ---
        val isProgression = (hint.itemFlags and 1) != 0
        val isUseful = (hint.itemFlags and 2) != 0

        val matchesType = if (isProgression) {
            showProgression
        } else if (isUseful) {
            showUseful
        } else {
            false
        }

        // Note: HintEntity does not have receivingGame, so we just match on itemName
        val isIgnored = ignoreList.any { ignoreRule ->
            ignoreRule.gameName.isNullOrBlank() && ignoreRule.itemName.equals(hint.itemName, ignoreCase = true)
        }
        val matchesIgnored = showIgnoredItems || !isIgnored

        matchesRoom && matchesQuery && matchesFinished && matchesPlayer && matchesType && matchesIgnored
    }
}

@Composable
fun SectionHeader(
    title: String,
    count: Int,
    isExpanded: Boolean,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = "$title ($count)",
            style = MaterialTheme.typography.titleMedium,
        )
        Icon(
            imageVector = if (isExpanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
            contentDescription = if (isExpanded) "Collapse" else "Expand"
        )
    }
}

private fun formatTimestamp(isoString: String, formatter: DateTimeFormatter): String {
    return try {
        var cleanString = isoString.trim()

        if (cleanString.contains(" ") && !cleanString.contains("T")) {
            cleanString = cleanString.replace(" ", "T")
        }

        val hasTimeZone = cleanString.endsWith("Z") ||
                (cleanString.indexOfAny(charArrayOf('+', '-'), 10) != -1)

        if (!hasTimeZone) {
            cleanString += "Z"
        }
        val instant = Instant.parse(cleanString)

        instant.atZone(ZoneId.systemDefault()).format(formatter)
    } catch (e: Exception) {
        Log.e("TimestampFormat", "Failed to parse timestamp: '$isoString'", e)
        "Invalid date"
    }
}