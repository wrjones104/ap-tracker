package com.jones.aptracker.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.ui.theme.APTheme

/**
 * Every item a tracked slot has received, one line per item name with its count (#465).
 * Read from the items cached on this device, so it needs no network and only exists for
 * tracked slots, the same as Slot Details.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ItemSummaryScreen(
    roomDbId: Int,
    slotId: Int,
    onBackClick: () -> Unit,
    userViewModel: UserViewModel
) {
    val rooms by userViewModel.trackedSlotsByRoom.collectAsState()
    val slot = rooms.find { it.room_db_id == roomDbId }?.tracked_slots?.find { it.slot_id == slotId }
    val slotName = slot?.let { if (it.player_alias.isNullOrBlank()) it.player_name else it.player_alias }

    val context = LocalContext.current
    val summaryFlow = remember(roomDbId, slotId) {
        AppDatabase.getInstance(context).historyDao().observeItemSummaryForSlot(roomDbId, slotId)
    }
    val rows by summaryFlow.collectAsState(initial = null)
    var sort by rememberSaveable { mutableStateOf(ItemSummarySort.RECENT) }
    val entries = remember(rows) { rows?.let(::toItemSummary) }
    val sorted = remember(entries, sort) { entries?.let { sortItemSummary(it, sort) } }

    // A keyed list keeps the row that was on top in view when the order changes, which would
    // leave the new sort's first rows scrolled off above it.
    val listState = rememberLazyListState()
    LaunchedEffect(sort) { listState.scrollToItem(0) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("Items Received", style = MaterialTheme.typography.titleMedium)
                        if (slotName != null) {
                            Text(
                                slotName,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                        }
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        },
        containerColor = MaterialTheme.colorScheme.background
    ) { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxSize()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    "Sort",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                ItemSummarySort.entries.forEach { option ->
                    FilterChip(
                        selected = sort == option,
                        onClick = { sort = option },
                        label = { Text(option.label) }
                    )
                }
            }

            when {
                sorted == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
                sorted.isEmpty() -> Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
                    Text(
                        "No items received yet.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                else -> {
                    val total = sorted.sumOf { it.count }
                    Text(
                        "$total ${if (total == 1) "item" else "items"} · ${sorted.size} different",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
                    )
                    LazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
                        items(sorted, key = { it.itemName }) { entry ->
                            ItemSummaryRow(entry)
                            HorizontalDivider()
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ItemSummaryRow(entry: ItemSummaryEntry) {
    // Same colouring as the Activity feed.
    val itemColor = when {
        (entry.itemFlags and 1) != 0 -> APTheme.colors.progression
        (entry.itemFlags and 2) != 0 -> APTheme.colors.useful
        (entry.itemFlags and 4) != 0 -> APTheme.colors.trap
        else -> Color.Unspecified
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                entry.itemName,
                style = MaterialTheme.typography.bodyLarge,
                color = itemColor
            )
            Text(
                "Last ${formatRelativeTime(entry.latestTimestamp)}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        Spacer(Modifier.width(16.dp))
        Text(
            "×${entry.count}",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold
        )
    }
}
