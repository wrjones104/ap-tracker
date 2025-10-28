package com.jones.aptracker.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.animation.AnimatedVisibility // <-- NEW IMPORT
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.KeyboardArrowDown // <-- NEW IMPORT
import androidx.compose.material.icons.filled.KeyboardArrowUp // <-- NEW IMPORT
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable // <-- NEW IMPORT
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.accompanist.swiperefresh.SwipeRefresh
import com.google.accompanist.swiperefresh.rememberSwipeRefreshState
import com.jones.aptracker.network.HintEntity
import com.jones.aptracker.network.HistoryItem
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle // For localized time format
import android.util.Log
import com.jones.aptracker.ui.getIconByName

// Main screen composable
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun HistoryScreen(
    roomId: Int?,
    roomAlias: String?,
    historyViewModel: HistoryViewModel = viewModel(),
    onBackClick: () -> Unit // Add callback for back navigation
) {
    // Load data when screen first appears or roomId changes
    LaunchedEffect(key1 = roomId) {
        historyViewModel.loadHistoryFor(roomId)
    }

    val isLoading by historyViewModel.isLoading.collectAsState()
    val errorMessage by historyViewModel.errorMessage
    val searchQuery by historyViewModel.searchQuery
    val coroutineScope = rememberCoroutineScope()

    // --- NEW: Collect the toggle state from ViewModel ---
    val showFoundHints by historyViewModel.showFoundHints.collectAsState()

    // State for tabs
    val tabTitles = listOf("Items", "Hints")

    // --- FIX: Use lambda for pageCount ---
    val pagerState = rememberPagerState(pageCount = { tabTitles.size })
    // --- END FIX ---

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(roomAlias ?: "Global History") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) { // Add back button
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        // SwipeRefresh for manual refresh
        val swipeRefreshState = rememberSwipeRefreshState(isRefreshing = isLoading)
        SwipeRefresh(
            state = swipeRefreshState,
            onRefresh = { historyViewModel.refreshAllHistory() },
            modifier = Modifier.padding(padding) // Apply padding here
        ) {
            Column(modifier = Modifier.fillMaxSize()) { // Main content column
                // Search Bar
                TextField(
                    value = searchQuery,
                    onValueChange = { historyViewModel.onSearchQueryChanged(it) },
                    label = { Text("Search History") },
                    leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 8.dp)
                )

                // Error Message Display
                errorMessage?.let {
                    Text(
                        text = it,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
                    )
                }

                // --- NEW: "Show Found" Toggle ---
                // This will only be visible when the "Hints" tab (page 1) is selected
                AnimatedVisibility(visible = pagerState.currentPage == 1) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable {
                                // --- LOGGING ---
                                Log.d("HintToggleDebug", "Row TAPPED, setting showFoundHints to ${!showFoundHints}")
                                // ---
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
                                // --- LOGGING ---
                                Log.d("HintToggleDebug", "Switch CHANGED, setting showFoundHints to $it")
                                // ---
                                historyViewModel.setShowFoundHints(it)
                            }
                        )
                    }
                }
                // --- END NEW ---

                // Tab Row
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

                // Horizontal Pager for Tab Content
                HorizontalPager(
                    state = pagerState,
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f) // Takes remaining space
                ) { page ->
                    when (page) {
                        0 -> ItemHistoryTab(historyViewModel = historyViewModel, searchQuery = searchQuery)
                        1 -> HintHistoryTab(historyViewModel = historyViewModel, searchQuery = searchQuery)
                    }
                }
            } // End Column
        } // End SwipeRefresh
    } // End Scaffold
}

// Composable for the Item History Tab
@Composable
fun ItemHistoryTab(historyViewModel: HistoryViewModel, searchQuery: String) {
    val fullHistory by historyViewModel.itemHistory.collectAsState()
    val context = LocalContext.current
    val formatter = remember { // Remember formatter for efficiency
        DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT)
            .withZone(ZoneId.systemDefault())
    }

    // Filter items based on search query
    val itemsToShow = remember(fullHistory, searchQuery) {
        if (searchQuery.isBlank()) {
            fullHistory
        } else {
            fullHistory.filter {
                it.message.contains(searchQuery, ignoreCase = true)
            }
        }
    }

    if (itemsToShow.isEmpty() && !historyViewModel.isLoading.collectAsState().value) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("No item history found.")
        }
    } else {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            items(itemsToShow, key = { it.timestamp + it.message }) { item -> // Use a more unique key
                val isClickable = item.tracker_id != null && item.slot_id != null
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable(enabled = isClickable) {
                            if (isClickable) {
                                // Original tracker URL logic
                                val url = "https://archipelago.gg/tracker/${item.tracker_id}/0/${item.slot_id}"
                                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                                context.startActivity(intent)
                            }
                        },
                    elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
                ) {
                    Row(
                        modifier = Modifier.padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon( // Using getIconByName from RoomsScreen, might need to move it
                            imageVector = getIconByName(item.icon_name),
                            contentDescription = "Item received",
                            tint = MaterialTheme.colorScheme.primary
                        )
                        Spacer(modifier = Modifier.width(16.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = item.message,
                                style = MaterialTheme.typography.bodyLarge
                            )
                            Text(
                                text = formatTimestamp(item.timestamp, formatter),
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

// Composable for the Hint History Tab
@Composable
fun HintHistoryTab(historyViewModel: HistoryViewModel, searchQuery: String) {
    val hintsForYou by historyViewModel.hintsForYou.collectAsState()
    val hintsByYou by historyViewModel.hintsByYou.collectAsState()
    val formatter = remember { // Remember formatter
        DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT)
            .withZone(ZoneId.systemDefault())
    }

    // --- NEW: State for collapsible sections ---
    var isForYouExpanded by rememberSaveable { mutableStateOf(true) }
    var isByYouExpanded by rememberSaveable { mutableStateOf(true) }
    // ---

    // Filter hints based on search query (apply to both lists)
    val filteredHintsForYou = remember(hintsForYou, searchQuery) {
        filterHints(hintsForYou, searchQuery)
    }
    val filteredHintsByYou = remember(hintsByYou, searchQuery) {
        filterHints(hintsByYou, searchQuery)
    }

    if (filteredHintsForYou.isEmpty() && filteredHintsByYou.isEmpty() && !historyViewModel.isLoading.collectAsState().value) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("No hint history found.")
        }
    } else {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp) // Slightly more space for sections
        ) {
            // Section: Hints For You
            if (filteredHintsForYou.isNotEmpty()) {
                item {
                    // --- NEW: Use SectionHeader ---
                    SectionHeader(
                        title = "Hints For Your Items",
                        count = filteredHintsForYou.size,
                        isExpanded = isForYouExpanded,
                        onClick = { isForYouExpanded = !isForYouExpanded }
                    )
                }
                // --- NEW: Conditionally show items ---
                if (isForYouExpanded) {
                    items(filteredHintsForYou, key = { it.hint_db_id }) { hint ->
                        HintCard(hint = hint, formatter = formatter, type = "for_you")
                    }
                }
            }

            // Section: Hints By You (for items in your world)
            if (filteredHintsByYou.isNotEmpty()) {
                item {
                    // Add spacing if both sections are present
                    if (filteredHintsForYou.isNotEmpty()) {
                        Spacer(Modifier.height(16.dp))
                        Divider()
                        Spacer(Modifier.height(16.dp))
                    }
                    // --- NEW: Use SectionHeader ---
                    SectionHeader(
                        title = "Hints For Items In Your World",
                        count = filteredHintsByYou.size,
                        isExpanded = isByYouExpanded,
                        onClick = { isByYouExpanded = !isByYouExpanded }
                    )
                }
                // --- NEW: Conditionally show items ---
                if (isByYouExpanded) {
                    items(filteredHintsByYou, key = { it.hint_db_id }) { hint ->
                        HintCard(hint = hint, formatter = formatter, type = "by_you")
                    }
                }
            }
        }
    }
}

// Helper function to filter hints
private fun filterHints(hints: List<HintEntity>, query: String): List<HintEntity> {
    if (query.isBlank()) return hints
    return hints.filter {
        it.itemName.contains(query, ignoreCase = true) ||
                it.locationName.contains(query, ignoreCase = true) ||
                it.itemOwnerName.contains(query, ignoreCase = true) ||
                it.locationOwnerName.contains(query, ignoreCase = true) ||
                it.roomAlias.contains(query, ignoreCase = true)
    }
}

// --- NEW COMPOSABLE ---
/**
 * A reusable, clickable header for a collapsible list section.
 */
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
            .padding(vertical = 8.dp), // Add padding for a larger click area
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
// --- END NEW COMPOSABLE ---


// Composable for displaying a single hint
@Composable
fun HintCard(hint: HintEntity, formatter: DateTimeFormatter, type: String) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
        colors = CardDefaults.cardColors(
            // Visual designation for found hints
            containerColor = if (hint.isFound) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.surface
        )
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            // Header Row (Room Alias + Timestamp)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = hint.roomAlias,
                    style = MaterialTheme.typography.labelMedium,
                    color = Color.Gray
                )
                Text(
                    text = formatTimestamp(hint.timestamp, formatter),
                    style = MaterialTheme.typography.labelMedium,
                    color = Color.Gray
                )
            }
            Spacer(Modifier.height(8.dp))

            // Main Hint Text (varies based on type)
            if (type == "for_you") {
                Text(
                    "Your ${hint.itemName}", // Item is yours
                    style = MaterialTheme.typography.bodyLarge
                )
                Text(
                    "is at ${hint.locationOwnerName}'s ${hint.locationName}", // Location belongs to someone else
                    style = MaterialTheme.typography.bodyMedium
                )
            } else { // "by_you"
                Text(
                    "${hint.itemOwnerName}'s ${hint.itemName}", // Item belongs to someone else
                    style = MaterialTheme.typography.bodyLarge
                )
                Text(
                    "is at your ${hint.locationName}", // Location is yours
                    style = MaterialTheme.typography.bodyMedium
                )
            }

            // Visual designation "Found!" text
            if (hint.isFound) {
                Spacer(Modifier.height(4.dp))
                Text(
                    "Found!",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary
                )
            }
        }
    }
}


// Helper function to format timestamp (moved outside HistoryList for reuse)
private fun formatTimestamp(isoString: String, formatter: DateTimeFormatter): String {
    return try {
        val instant = Instant.parse(isoString)
        instant.atZone(ZoneId.systemDefault()).format(formatter) // Use formatter directly
    } catch (e: Exception) {
        Log.e("TimestampFormat", "Failed to parse timestamp: $isoString", e)
        "Invalid date" // Fallback
    }
}