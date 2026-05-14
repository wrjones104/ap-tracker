package com.jones.aptracker.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.FilterList
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.UnfoldLess
import androidx.compose.material.icons.filled.UnfoldMore
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.accompanist.swiperefresh.SwipeRefresh
import com.google.accompanist.swiperefresh.rememberSwipeRefreshState
import com.jones.aptracker.network.RoomWithTrackedSlots
import com.jones.aptracker.network.TrackedSlotDetail
import java.time.Duration
import java.time.Instant

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SlotsScreen(
    userViewModel: UserViewModel = viewModel(),
    onSlotClick: (roomDbId: Int, slotId: Int) -> Unit
) {
    val trackedSlotsByRoom by userViewModel.trackedSlotsByRoom.collectAsState()
    val isLoading = trackedSlotsByRoom.isEmpty() // simple loading heuristic

    LaunchedEffect(Unit) {
        userViewModel.fetchTrackedSlots()
    }

    var searchQuery by remember { mutableStateOf("") }
    var showFinished by remember { mutableStateOf(true) }
    val expandedRooms = remember { mutableStateMapOf<Int, Boolean>() }
    var allExpanded by remember { mutableStateOf(true) }

    // Filter: hide archived rooms
    val activeRooms = remember(trackedSlotsByRoom) {
        trackedSlotsByRoom.filter { !it.is_archived }
    }

    // Apply search and finished filters
    val filteredRooms = remember(activeRooms, searchQuery, showFinished) {
        activeRooms.mapNotNull { room ->
            val filteredSlots = room.tracked_slots.filter { slot ->
                val matchesSearch = searchQuery.isBlank() ||
                        slot.player_name.contains(searchQuery, ignoreCase = true) ||
                        (slot.player_alias?.contains(searchQuery, ignoreCase = true) == true) ||
                        (slot.game?.contains(searchQuery, ignoreCase = true) == true)
                val matchesFinished = showFinished || !slot.is_finished
                matchesSearch && matchesFinished
            }
            if (filteredSlots.isNotEmpty()) {
                room.copy(tracked_slots = filteredSlots)
            } else {
                null
            }
        }
    }

    // Initialize expand state for new rooms
    filteredRooms.forEach { room ->
        if (room.room_db_id !in expandedRooms) {
            expandedRooms[room.room_db_id] = true
        }
    }

    Scaffold(
        contentWindowInsets = WindowInsets(0.dp)
    ) { innerPadding ->
        SwipeRefresh(
            state = rememberSwipeRefreshState(isRefreshing = false),
            onRefresh = { userViewModel.fetchTrackedSlots() },
            modifier = Modifier.padding(innerPadding)
        ) {
            Column(modifier = Modifier.fillMaxSize()) {
                // --- Search Bar ---
                TextField(
                    value = searchQuery,
                    onValueChange = { searchQuery = it },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    label = { Text("Search by player, alias, or game") },
                    leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                    singleLine = true
                )

                // --- Filter Row ---
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 4.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterChip(
                            selected = showFinished,
                            onClick = { showFinished = !showFinished },
                            label = { Text("Show Finished") },
                            leadingIcon = if (showFinished) {
                                { Text("🏁", style = MaterialTheme.typography.labelSmall) }
                            } else null
                        )

                        // Slot count badge
                        val totalSlots = filteredRooms.sumOf { it.tracked_slots.size }
                        Text(
                            text = "$totalSlots slot${if (totalSlots != 1) "s" else ""}",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.align(Alignment.CenterVertically)
                        )
                    }

                    // Expand/Collapse All toggle
                    IconButton(onClick = {
                        allExpanded = !allExpanded
                        filteredRooms.forEach { room ->
                            expandedRooms[room.room_db_id] = allExpanded
                        }
                    }) {
                        Icon(
                            imageVector = if (allExpanded) Icons.Default.UnfoldLess else Icons.Default.UnfoldMore,
                            contentDescription = if (allExpanded) "Collapse All" else "Expand All"
                        )
                    }
                }

                // --- Main Content ---
                if (activeRooms.isEmpty() && !isLoading) {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(
                                text = "No tracked slots",
                                style = MaterialTheme.typography.titleMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Text(
                                text = "Track slots from the Rooms tab to see them here.",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                } else if (filteredRooms.isEmpty() && searchQuery.isNotBlank()) {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(
                            text = "No slots match your search.",
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                } else {
                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(
                            start = 8.dp, top = 4.dp, end = 8.dp, bottom = 80.dp
                        )
                    ) {
                        filteredRooms.forEach { room ->
                            val isExpanded = expandedRooms[room.room_db_id] ?: true

                            // Room Group Header
                            item(key = "header_${room.room_db_id}") {
                                RoomGroupHeader(
                                    room = room,
                                    isExpanded = isExpanded,
                                    onToggleExpand = {
                                        expandedRooms[room.room_db_id] = !isExpanded
                                    }
                                )
                            }

                            // Slot Cards (animated visibility)
                            if (isExpanded) {
                                items(
                                    items = room.tracked_slots,
                                    key = { "${room.room_db_id}_${it.slot_id}" }
                                ) { slot ->
                                    SlotCard(
                                        slot = slot,
                                        onClick = { onSlotClick(room.room_db_id, slot.slot_id) }
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun RoomGroupHeader(
    room: RoomWithTrackedSlots,
    isExpanded: Boolean,
    onToggleExpand: () -> Unit
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp)
            .clickable(onClick = onToggleExpand),
        color = MaterialTheme.colorScheme.surfaceVariant,
        shape = RoundedCornerShape(8.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = getIconByName(room.icon_name),
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(24.dp)
            )
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = room.room_alias,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                if (room.host != null) {
                    Text(
                        text = room.host,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                    )
                }
            }
            // Slot count badge
            Surface(
                color = MaterialTheme.colorScheme.primary.copy(alpha = 0.12f),
                shape = RoundedCornerShape(12.dp)
            ) {
                Text(
                    text = "${room.tracked_slots.size}",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.primary,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp)
                )
            }
            Spacer(Modifier.width(4.dp))
            Icon(
                imageVector = if (isExpanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                contentDescription = if (isExpanded) "Collapse" else "Expand",
                tint = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
fun SlotCard(
    slot: TrackedSlotDetail,
    onClick: () -> Unit
) {
    val isDark = isSystemInDarkTheme()
    val finishedColor = if (isDark) Color(0xFF81C784) else Color(0xFF0E8A0E)

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 16.dp, end = 0.dp, top = 2.dp, bottom = 2.dp)
            .clickable(onClick = onClick),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                // Player name with finished styling
                val displayName = if (slot.player_alias.isNullOrBlank()) {
                    slot.player_name
                } else {
                    "${slot.player_alias} (${slot.player_name})"
                }

                Text(
                    text = if (slot.is_finished) "🏁 $displayName" else displayName,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Medium,
                    color = if (slot.is_finished) finishedColor else Color.Unspecified
                )

                // Game name
                if (!slot.game.isNullOrBlank()) {
                    Text(
                        text = slot.game,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }

                // Last activity
                if (slot.last_activity != null) {
                    Text(
                        text = "Last activity: ${formatRelativeTime(slot.last_activity)}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                    )
                }
            }

            Icon(
                imageVector = Icons.Default.ChevronRight,
                contentDescription = "View Details",
                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
            )
        }
    }
}

/**
 * Formats an ISO-8601 timestamp into a human-friendly relative time string.
 */
fun formatRelativeTime(isoTimestamp: String): String {
    return try {
        val instant = Instant.parse(isoTimestamp)
        val now = Instant.now()
        val duration = Duration.between(instant, now)

        when {
            duration.toMinutes() < 1 -> "just now"
            duration.toMinutes() < 60 -> "${duration.toMinutes()}m ago"
            duration.toHours() < 24 -> "${duration.toHours()}h ago"
            duration.toDays() < 7 -> "${duration.toDays()}d ago"
            duration.toDays() < 30 -> "${duration.toDays() / 7}w ago"
            else -> "${duration.toDays() / 30}mo ago"
        }
    } catch (e: Exception) {
        "Unknown"
    }
}
