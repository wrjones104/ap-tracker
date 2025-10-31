package com.jones.aptracker.ui

import android.content.Intent
import android.net.Uri
import android.util.Log
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Divider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TopAppBar
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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.accompanist.swiperefresh.SwipeRefresh
import com.google.accompanist.swiperefresh.rememberSwipeRefreshState
import com.jones.aptracker.network.HintEntity
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
    val searchQuery by historyViewModel.searchQuery
    val coroutineScope = rememberCoroutineScope()

    val showFoundHints by historyViewModel.showFoundHints.collectAsState()

    val tabTitles = listOf("Items", "Hints")

    val pagerState = rememberPagerState(pageCount = { tabTitles.size })

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

                errorMessage?.let {
                    Text(
                        text = it,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
                    )
                }

                AnimatedVisibility(visible = pagerState.currentPage == 1) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable {
                                Log.d("HintToggleDebug", "Row TAPPED, setting showFoundHints to ${!showFoundHints}")
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
                                Log.d("HintToggleDebug", "Switch CHANGED, setting showFoundHints to $it")
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
                        0 -> ItemHistoryTab(historyViewModel = historyViewModel, searchQuery = searchQuery)
                        1 -> HintHistoryTab(historyViewModel = historyViewModel, searchQuery = searchQuery)
                    }
                }
            }
        }
    }
}

@Composable
fun ItemHistoryTab(historyViewModel: HistoryViewModel, searchQuery: String) {
    val fullHistory by historyViewModel.itemHistory.collectAsState()
    val context = LocalContext.current
    val formatter = remember {
        DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT)
            .withZone(ZoneId.systemDefault())
    }

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
            items(itemsToShow, key = { it.timestamp + it.message }) { item ->
                val isClickable = item.tracker_id != null && item.slot_id != null
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable(enabled = isClickable) {
                            if (isClickable) {
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
                        Icon(
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

@Composable
fun HintHistoryTab(historyViewModel: HistoryViewModel, searchQuery: String) {
    val hintsForYou by historyViewModel.hintsForYou.collectAsState()
    val hintsByYou by historyViewModel.hintsByYou.collectAsState()
    val formatter = remember { // Remember formatter
        DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT)
            .withZone(ZoneId.systemDefault())
    }

    var isForYouExpanded by rememberSaveable { mutableStateOf(true) }
    var isByYouExpanded by rememberSaveable { mutableStateOf(true) }

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
                        HintCard(hint = hint, formatter = formatter, type = "for_you")
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
                        HintCard(hint = hint, formatter = formatter, type = "by_you")
                    }
                }
            }
        }
    }
}

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


@Composable
fun HintCard(hint: HintEntity, formatter: DateTimeFormatter, type: String) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (hint.isFound) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.surface
        )
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
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

            if (type == "for_you") {
                Text(
                    "Your ${hint.itemName}",
                    style = MaterialTheme.typography.bodyLarge
                )
                Text(
                    "is at ${hint.locationOwnerName}'s ${hint.locationName}",
                    style = MaterialTheme.typography.bodyMedium
                )
            } else {
                Text(
                    "${hint.itemOwnerName}'s ${hint.itemName}",
                    style = MaterialTheme.typography.bodyLarge
                )
                Text(
                    "is at your ${hint.locationName}",
                    style = MaterialTheme.typography.bodyMedium
                )
            }

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


private fun formatTimestamp(isoString: String, formatter: DateTimeFormatter): String {
    return try {
        val instant = Instant.parse(isoString)
        instant.atZone(ZoneId.systemDefault()).format(formatter)
    } catch (e: Exception) {
        Log.e("TimestampFormat", "Failed to parse timestamp: $isoString", e)
        "Invalid date"
    }
}