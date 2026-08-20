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
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Flag
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
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.accompanist.swiperefresh.SwipeRefresh
import com.google.accompanist.swiperefresh.rememberSwipeRefreshState
import com.jones.aptracker.data.FinishedResolver
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
    val showFinished by userViewModel.slotsShowFinished.collectAsState()
    val finishedResolver by userViewModel.finishedResolver.collectAsState()
    val expandedRoomIds by userViewModel.expandedRoomIds.collectAsState()
    // Filter: hide archived rooms
    val activeRooms = remember(trackedSlotsByRoom) {
        trackedSlotsByRoom.filter { !it.is_archived }
    }

    val allExpanded = remember(expandedRoomIds, activeRooms) {
        activeRooms.isNotEmpty() && activeRooms.all { it.room_db_id in expandedRoomIds }
    }

    val filteredRooms = remember(activeRooms, searchQuery, showFinished, finishedResolver) {
        buildRoomSlotGroups(activeRooms, searchQuery, showFinished, finishedResolver)
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
                            onClick = { userViewModel.setSlotsShowFinished(!showFinished) },
                            label = { Text("Show Finished") },
                            leadingIcon = if (showFinished) {
                                {
                                    Icon(
                                        imageVector = Icons.Filled.Flag,
                                        contentDescription = null,
                                        modifier = Modifier.size(16.dp)
                                    )
                                }
                            } else null
                        )

                        // Slot count badge
                        val totalSlots = filteredRooms.sumOf { it.visibleSlots.size }
                        Text(
                            text = "$totalSlots slot${if (totalSlots != 1) "s" else ""}",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.align(Alignment.CenterVertically)
                        )
                    }

                    // Expand/Collapse All toggle
                    IconButton(onClick = {
                        userViewModel.setAllRoomsExpanded(filteredRooms.map { it.room.room_db_id }, !allExpanded)
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
                        filteredRooms.forEach { group ->
                            val room = group.room
                            val isExpanded = room.room_db_id in expandedRoomIds

                            // Room Group Header
                            item(key = "header_${room.room_db_id}") {
                                RoomGroupHeader(
                                    room = room,
                                    activeCount = group.activeCount,
                                    finishedCount = group.finishedCount,
                                    isExpanded = isExpanded,
                                    onToggleExpand = {
                                        userViewModel.setRoomExpanded(room.room_db_id, !isExpanded)
                                    }
                                )
                            }

                            // Shown whenever this room has slots the filter is holding
                            // back -- not only when it has nothing left to show. Appearing
                            // in just the all-hidden case made the count look global, since
                            // there was no visible slot list to read it against.
                            if (isExpanded && group.hiddenFinishedCount > 0) {
                                item(key = "finished_${room.room_db_id}") {
                                    HiddenFinishedSlotsRow(
                                        count = group.hiddenFinishedCount,
                                        onShowFinished = { userViewModel.setSlotsShowFinished(true) }
                                    )
                                }
                            }

                            // Slot Cards (animated visibility)
                            if (isExpanded) {
                                items(
                                    items = group.visibleSlots,
                                    key = { "${room.room_db_id}_${it.slot_id}" }
                                ) { slot ->
                                    SlotCard(
                                        slot = slot,
                                        isFinished = finishedResolver.isFinished(
                                            roomDbId = room.room_db_id,
                                            slotId = slot.slot_id,
                                            isGoaled = slot.is_finished,
                                            hasAllChecks = slot.has_all_checks
                                        ),
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

/**
 * Group each room's slots for display, applying the search and finished filters.
 *
 * The two filters are deliberately not equivalent, and that asymmetry is the point:
 *
 * - A room whose slots no longer match the **search** is dropped. That is what searching
 *   means.
 * - A room whose slots are merely all **finished** is never dropped. A room vanishing the
 *   moment its last slot completes reads as the app losing it; a room leaving the list
 *   should only ever be a user action (archive or delete).
 *
 * Extracted from the composable so that asymmetry is pinned by tests -- collapsing the two
 * back into one filter is exactly the regression that made finished rooms disappear.
 */
internal fun buildRoomSlotGroups(
    rooms: List<RoomWithTrackedSlots>,
    searchQuery: String,
    showFinished: Boolean,
    finishedResolver: FinishedResolver
): List<RoomSlotGroup> = rooms.mapNotNull { room ->
    val searchMatches = room.tracked_slots.filter { slot ->
        searchQuery.isBlank() ||
                slot.player_name.contains(searchQuery, ignoreCase = true) ||
                (slot.player_alias?.contains(searchQuery, ignoreCase = true) == true) ||
                (slot.game?.contains(searchQuery, ignoreCase = true) == true)
    }
    if (searchMatches.isEmpty()) return@mapNotNull null

    // "Finished" is the user's own definition, not just goaled -- which is the whole
    // point for release-off rooms, where a goaled slot may still have items to send.
    //
    // Partitioned rather than filtered so the finished count is known even when finished
    // slots are being shown. The header reports the room's real makeup either way; it is
    // not a count of what happens to be on screen.
    val (finished, active) = searchMatches.partition { slot ->
        finishedResolver.isFinished(
            roomDbId = room.room_db_id,
            slotId = slot.slot_id,
            isGoaled = slot.is_finished,
            hasAllChecks = slot.has_all_checks
        )
    }

    RoomSlotGroup(
        room = room,
        visibleSlots = if (showFinished) searchMatches else active,
        totalCount = searchMatches.size,
        finishedCount = finished.size
    )
}

/**
 * One room's row in the slots list, with its slots already filtered.
 *
 * Carries [hiddenFinishedCount] so the list can tell "this room has nothing to show"
 * apart from "this room's slots are all finished and currently hidden" -- the second is
 * worth explaining to the user rather than silently rendering an empty room.
 */
internal data class RoomSlotGroup(
    val room: RoomWithTrackedSlots,
    val visibleSlots: List<TrackedSlotDetail>,
    val totalCount: Int,
    val finishedCount: Int
) {
    val activeCount: Int get() = totalCount - finishedCount

    /** Slots the finished filter is currently holding back. Zero when they are shown. */
    val hiddenFinishedCount: Int get() = totalCount - visibleSlots.size

    /**
     * Every slot the room has is finished, and finished slots are hidden.
     *
     * The list itself keys off [hiddenFinishedCount]; this exists so the tests can state
     * the "all finished" case directly, which is the one that used to drop the room.
     */
    val isAllFinished: Boolean get() = visibleSlots.isEmpty() && finishedCount > 0
}

/**
 * A room's active/finished makeup: a proportional bar and a plain-language count.
 *
 * Laid out under the room name rather than beside it. A trailing indicator competes with
 * the alias for horizontal space and truncates long room names on narrow screens; the
 * header only renders once per room, so a line costs little.
 */
@Composable
private fun RoomSlotProgress(activeCount: Int, finishedCount: Int) {
    val total = activeCount + finishedCount
    if (total == 0) return

    val isDark = isSystemInDarkTheme()
    val finishedColor = if (isDark) Color(0xFF81C784) else Color(0xFF0E8A0E)
    val allFinished = activeCount == 0

    val summary = when {
        allFinished -> "All $total finished"
        finishedCount == 0 -> "$activeCount active"
        else -> "$activeCount active · $finishedCount finished"
    }

    Row(
        modifier = Modifier
            .padding(top = 5.dp)
            // The bar reads as a proportion, so a screen reader needs the numbers said
            // outright; clearMergedSemantics would otherwise announce the row piecemeal.
            .semantics(mergeDescendants = true) { contentDescription = summary },
        verticalAlignment = Alignment.CenterVertically
    ) {
        LinearProgressIndicator(
            progress = { finishedCount.toFloat() / total },
            modifier = Modifier
                .width(72.dp)
                .height(4.dp)
                .clip(RoundedCornerShape(2.dp)),
            color = if (allFinished) finishedColor else MaterialTheme.colorScheme.primary,
            trackColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.24f),
            gapSize = 0.dp,
            drawStopIndicator = {}
        )
        Spacer(Modifier.width(8.dp))
        Text(
            text = summary,
            style = MaterialTheme.typography.labelSmall,
            color = if (allFinished) finishedColor else MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

/**
 * Accounts for the slots the finished filter is holding back in one room.
 *
 * Scoped to its room, which is why the copy says so outright -- the count is easy to read
 * as a screen-wide total otherwise, and it will not match one when several rooms each have
 * finished slots hidden.
 *
 * Sits directly under the room header, above the slots that did survive the filter, so the
 * explanation is next to the header count it accounts for. When the room has nothing else
 * left to show, this row is also what keeps it from rendering as an empty room: it used to
 * vanish from the list entirely the moment its last slot completed.
 */
@Composable
private fun HiddenFinishedSlotsRow(count: Int, onShowFinished: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 16.dp, end = 8.dp, top = 4.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = Icons.Filled.CheckCircle,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(16.dp)
        )
        Spacer(Modifier.width(8.dp))
        Text(
            // "in this room" is doing real work: the row is room-scoped but sits at the
            // bottom of a room's slots, where an unqualified count reads as a total for
            // the whole screen.
            text = if (count == 1) {
                "1 finished slot hidden in this room"
            } else {
                "$count finished slots hidden in this room"
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f)
        )
        TextButton(onClick = onShowFinished) {
            Text("Show")
        }
    }
}

@Composable
fun RoomGroupHeader(
    room: RoomWithTrackedSlots,
    activeCount: Int,
    finishedCount: Int,
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

                // Always present, whatever the finished filter is doing. This is the
                // room's real makeup, and it is what tells you slots exist that the
                // filter is currently hiding -- the bare count badge that used to sit
                // here could not, because it only ever described what was on screen.
                RoomSlotProgress(activeCount = activeCount, finishedCount = finishedCount)
            }
            Spacer(Modifier.width(8.dp))
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
    /** Finished under the user's own definition, not merely goaled. */
    isFinished: Boolean,
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

                // Two distinguishable states rather than one flag: a goaled slot that
                // still has items to send is not the same thing as a drained one, and
                // under some definitions the first stays visible. Icons carry a
                // contentDescription, so this no longer depends on color alone.
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (slot.is_finished || slot.has_all_checks == true) {
                        val fullyDone = slot.is_finished && slot.has_all_checks == true
                        Icon(
                            imageVector = if (fullyDone) Icons.Filled.CheckCircle else Icons.Filled.Flag,
                            contentDescription = when {
                                fullyDone -> "Goaled, no items left to send"
                                slot.is_finished -> "Goaled"
                                else -> "No items left to send"
                            },
                            tint = finishedColor,
                            modifier = Modifier.size(16.dp)
                        )
                        Spacer(Modifier.width(4.dp))
                    }
                    Text(
                        text = displayName,
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = FontWeight.Medium,
                        color = if (isFinished) finishedColor else Color.Unspecified
                    )
                }

                // Surfacing the counts is what makes the setting self-explanatory: it
                // shows *why* a goaled slot is still in the list. Worded as "checks" to
                // match the community term used by the finished-definition options.
                val checksDone = slot.checks_done
                val totalLocations = slot.total_locations
                if (checksDone != null && totalLocations != null && totalLocations > 0) {
                    Text(
                        text = "$checksDone/$totalLocations checks",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }

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
