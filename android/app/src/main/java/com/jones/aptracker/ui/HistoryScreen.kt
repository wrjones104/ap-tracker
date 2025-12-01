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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Divider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.accompanist.swiperefresh.SwipeRefresh
import com.google.accompanist.swiperefresh.rememberSwipeRefreshState
import com.jones.aptracker.network.HintEntity
import com.jones.aptracker.network.HistoryItem
import com.jones.aptracker.ui.theme.APTheme
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun HistoryScreen(
    roomId: Int?,
    roomAlias: String?,
    historyViewModel: HistoryViewModel = viewModel(),
    onBackClick: () -> Unit
) {
    LaunchedEffect(key1 = roomId) {
        historyViewModel.loadHistoryFor(roomId)
    }

    val isLoading by historyViewModel.isLoading.collectAsState()
    val errorMessage by historyViewModel.errorMessage
    val actionMessage by historyViewModel.actionMessage.collectAsState()
    val searchQuery by historyViewModel.searchQuery

    var selectedItem by remember { mutableStateOf<HistoryItem?>(null) }
    var selectedHint by remember { mutableStateOf<HintEntity?>(null) }
    val sheetState = rememberModalBottomSheetState()
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()

    val snackbarHostState = remember { SnackbarHostState() }

    // Handle Action Feedback (e.g. "Ignored Power Star")
    LaunchedEffect(actionMessage) {
        if (actionMessage != null) {
            snackbarHostState.showSnackbar(actionMessage!!)
            historyViewModel.clearActionMessage()
        }
    }

    LaunchedEffect(errorMessage) {
        if (errorMessage != null) {
            snackbarHostState.showSnackbar(
                message = errorMessage!!,
                duration = SnackbarDuration.Short
            )
            historyViewModel.clearErrorMessage()
        }
    }

    val showFoundHints by historyViewModel.showFoundHints.collectAsState()
    val showFinished by historyViewModel.showFinished.collectAsState()

    val tabTitles = listOf("Items", "Hints")
    val pagerState = rememberPagerState(pageCount = { tabTitles.size })

    Scaffold(
        snackbarHost = { SnackbarHost(hostState = snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text(roomAlias ?: "Global History") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        val swipeRefreshState = rememberSwipeRefreshState(isRefreshing = isLoading)
        SwipeRefresh(
            state = swipeRefreshState,
            onRefresh = { historyViewModel.refreshAllHistory() },
            modifier = Modifier.padding(padding)
        ) {
            Column(modifier = Modifier.fillMaxSize()) {
                TextField(
                    value = searchQuery,
                    onValueChange = { historyViewModel.onSearchQueryChanged(it) },
                    label = { Text("Search History") },
                    leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 8.dp)
                )

                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { historyViewModel.setShowFinished(!showFinished) }
                        .padding(horizontal = 16.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = "Show Finished Slots",
                        style = MaterialTheme.typography.bodyMedium
                    )
                    Switch(
                        checked = showFinished,
                        onCheckedChange = { historyViewModel.setShowFinished(it) }
                    )
                }

                AnimatedVisibility(visible = pagerState.currentPage == 1) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable {
                                historyViewModel.setShowFoundHints(!showFoundHints)
                            }
                            .padding(horizontal = 16.dp, vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text(
                            text = "Show Found Hints",
                            style = MaterialTheme.typography.bodyMedium
                        )
                        Switch(
                            checked = showFoundHints,
                            onCheckedChange = {
                                historyViewModel.setShowFoundHints(it)
                            }
                        )
                    }
                }

                TabRow(selectedTabIndex = pagerState.currentPage) {
                    tabTitles.forEachIndexed { index, title ->
                        Tab(
                            selected = pagerState.currentPage == index,
                            onClick = {
                                coroutineScope.launch { pagerState.animateScrollToPage(index) }
                            },
                            text = { Text(title) }
                        )
                    }
                }

                HorizontalPager(
                    state = pagerState,
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f)
                ) { page ->
                    when (page) {
                        0 -> ItemHistoryTab(
                            historyViewModel = historyViewModel,
                            searchQuery = searchQuery,
                            onItemClick = { item -> selectedItem = item }
                        )
                        1 -> HintHistoryTab(
                            historyViewModel = historyViewModel,
                            searchQuery = searchQuery,
                            onHintClick = { hint -> selectedHint = hint }
                        )
                    }
                }
            }
        }
    }

    if (selectedItem != null) {
        ModalBottomSheet(
            onDismissRequest = { selectedItem = null },
            sheetState = sheetState
        ) {
            HistoryDetailSheet(
                item = selectedItem!!,
                onOpenTracker = {
                    val cleanHost = (selectedItem!!.host?.takeIf { it.isNotBlank() }
                        ?: "archipelago.gg").removePrefix("https://")
                        .removePrefix("http://")
                    val url = "https://${cleanHost}/tracker/${selectedItem!!.tracker_id}/0/${selectedItem!!.slot_id}"
                    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                    context.startActivity(intent)
                    selectedItem = null
                },
                onIgnoreItem = { gameName: String? ->
                    // gameName null = Global, otherwise specific game
                    historyViewModel.ignoreItem(selectedItem!!.itemName, gameName)
                    selectedItem = null
                }
            )
        }
    }
    selectedHint?.let { hint ->
        ModalBottomSheet(
            onDismissRequest = { selectedHint = null },
            sheetState = sheetState
        ) {
            HintDetailSheet(
                hint = hint,
                onDismiss = { selectedHint = null }
            )
        }
    }
}

@Composable
fun HistoryDetailSheet(
    item: HistoryItem,
    onOpenTracker: () -> Unit,
    onIgnoreItem: (String?) -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(24.dp)
            .navigationBarsPadding()
    ) {
        // Header
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                imageVector = getIconByName(item.icon_name),
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(32.dp)
            )
            Spacer(Modifier.width(16.dp))
            Column {
                Text(
                    text = item.itemName,
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold
                )
                val displayPlayer = getDisplayName(item.playerName, item.playerAlias, useCondensed = false)

                Text(
                    text = "Received by $displayPlayer",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                if (!item.receivingGame.isNullOrBlank()) {
                    Text(
                        text = "Game: ${item.receivingGame}",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }

        Spacer(Modifier.height(24.dp))

        // Action 1: Open Tracker
        Button(
            onClick = onOpenTracker,
            modifier = Modifier.fillMaxWidth()
        ) {
            Icon(Icons.Default.OpenInNew, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text("Open in Web Tracker")
        }

        Spacer(Modifier.height(12.dp))

        // Action 2: Ignore Item (Game Specific)
        if (!item.receivingGame.isNullOrBlank()) {
            OutlinedButton(
                onClick = { onIgnoreItem(item.receivingGame) },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.outlinedButtonColors(
                    contentColor = MaterialTheme.colorScheme.error
                )
            ) {
                Icon(Icons.Default.VisibilityOff, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Text("Ignore '${item.itemName}' in ${item.receivingGame}")
            }
            Spacer(Modifier.height(8.dp))
        }

        // Action 3: Ignore Item (Global)
        OutlinedButton(
            onClick = { onIgnoreItem(null) },
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.outlinedButtonColors(
                contentColor = MaterialTheme.colorScheme.error
            )
        ) {
            Icon(Icons.Default.VisibilityOff, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text("Ignore '${item.itemName}' Globally (All Games)")
        }

        Spacer(Modifier.height(8.dp))

        Text(
            text = "Ignoring this will stop future push notifications for this item name.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth()
        )
    }
}



@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ItemHistoryTab(
    historyViewModel: HistoryViewModel,
    searchQuery: String,
    onItemClick: (HistoryItem) -> Unit
) {
    val fullHistory by historyViewModel.itemHistory.collectAsState()
    val availablePlayers by historyViewModel.availablePlayers.collectAsState()
    val selectedPlayer by historyViewModel.selectedPlayerFilter.collectAsState()
    val showFinished by historyViewModel.showFinished.collectAsState()
    val finishedKeys by historyViewModel.finishedPlayerKeys.collectAsState()
    val useCondensed by historyViewModel.useCondensed.collectAsState()

    val formatter = remember {
        DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT)
            .withZone(ZoneId.systemDefault())
    }

    val isDark = isSystemInDarkTheme()
    val finishedColor = if (isDark) Color(0xFF81C784) else Color(0xFF0E8A0E)

    val itemsToShow = remember(fullHistory, searchQuery, selectedPlayer, showFinished, finishedKeys) {
        fullHistory.filter { item ->
            val matchesSearch = searchQuery.isBlank() ||
                    item.playerName.contains(searchQuery, ignoreCase = true) ||
                    item.itemName.contains(searchQuery, ignoreCase = true)

            val matchesPlayer = selectedPlayer == null || item.playerName == selectedPlayer

            val isFinished = if (item.db_id != null) {
                finishedKeys.contains(item.db_id to item.playerName)
            } else {
                false
            }
            val matchesFinished = showFinished || !isFinished

            matchesSearch && matchesPlayer && matchesFinished
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        if (availablePlayers.isNotEmpty()) {
            LazyRow(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
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
fun HintHistoryTab(
    historyViewModel: HistoryViewModel,
    searchQuery: String,
    onHintClick: (HintEntity) -> Unit
) {
    val hintsForYou by historyViewModel.hintsForYou.collectAsState()
    val hintsByYou by historyViewModel.hintsByYou.collectAsState()
    val useCondensed by historyViewModel.useCondensed.collectAsState()
    val showFinished by historyViewModel.showFinished.collectAsState()
    val finishedKeys by historyViewModel.finishedPlayerKeys.collectAsState()

    val availablePlayers by historyViewModel.availableHintPlayers.collectAsState()
    val selectedPlayer by historyViewModel.selectedPlayerFilter.collectAsState()

    val formatter = remember {
        DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT)
            .withZone(ZoneId.systemDefault())
    }

    var isForYouExpanded by rememberSaveable { mutableStateOf(true) }
    var isByYouExpanded by rememberSaveable { mutableStateOf(true) }

    val filteredHintsForYou = remember(hintsForYou, searchQuery, showFinished, finishedKeys, selectedPlayer) {
        filterHints(hintsForYou, searchQuery, showFinished, finishedKeys, selectedPlayer)
    }
    val filteredHintsByYou = remember(hintsByYou, searchQuery, showFinished, finishedKeys, selectedPlayer) {
        filterHints(hintsByYou, searchQuery, showFinished, finishedKeys, selectedPlayer)
    }

    Column(modifier = Modifier.fillMaxSize()) {

        if (availablePlayers.isNotEmpty()) {
            LazyRow(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
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
                            Divider()
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
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = if (hint.isFound) Icons.Default.CheckCircle else Icons.Default.Info,
                contentDescription = if (hint.isFound) "Found" else "Hint",
                tint = if (hint.isFound) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
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
                            withStyle(style = SpanStyle(color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)) {
                                append("Found")
                            }
                            append(" • ")
                        }
                        append(formatTimestamp(hint.timestamp, formatter))
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
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
    selectedPlayer: String?
): List<HintEntity> {
    return hints.filter { hint ->
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

        matchesQuery && matchesFinished && matchesPlayer
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