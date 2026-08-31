package com.jones.aptracker.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Flag
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.jones.aptracker.data.FinishedResolver
import com.jones.aptracker.network.RoomWithTrackedSlots
import com.jones.aptracker.network.TrackMode
import com.jones.aptracker.network.TrackedSlotDetail
import java.time.Duration
import java.time.Instant

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
internal fun RoomSlotProgress(trackedLabel: String, activeCount: Int, finishedCount: Int) {
    val total = activeCount + finishedCount

    val isDark = isSystemInDarkTheme()
    val finishedColor = if (isDark) Color(0xFF81C784) else Color(0xFF0E8A0E)
    val allFinished = total > 0 && activeCount == 0

    // [trackedLabel] is how much of the room is being watched at all; the rest is how
    // those slots are going. A room with nothing tracked still shows the first half --
    // "0 of 9 tracked" is the whole reason to open that room.
    val summary = when {
        total == 0 -> trackedLabel
        allFinished -> "$trackedLabel · all $total finished"
        finishedCount == 0 -> "$trackedLabel · $activeCount active"
        else -> "$trackedLabel · $activeCount active, $finishedCount finished"
    }

    Row(
        modifier = Modifier
            .padding(top = 4.dp)
            // The bar reads as a proportion, so a screen reader needs the numbers said
            // outright; clearMergedSemantics would otherwise announce the row piecemeal.
            .semantics(mergeDescendants = true) { contentDescription = summary },
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (total > 0) {
            LinearProgressIndicator(
                progress = { finishedCount.toFloat() / total },
                modifier = Modifier
                    .width(40.dp)
                    .height(4.dp)
                    .clip(RoundedCornerShape(2.dp)),
                color = if (allFinished) finishedColor else MaterialTheme.colorScheme.primary,
                trackColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.24f),
                gapSize = 0.dp,
                drawStopIndicator = {}
            )
            Spacer(Modifier.width(8.dp))
        }
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
internal fun HiddenFinishedSlotsRow(count: Int, onShowFinished: () -> Unit) {
    val metrics = LocalLayoutMetrics.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = metrics.slotIndent, end = 8.dp, top = 4.dp, bottom = 4.dp),
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

/**
 * The way in to a room's slot selection, sitting at the bottom of that room's expanded
 * slots.
 *
 * Placed here on purpose. Adding and removing tracked slots used to live behind the
 * room's overflow menu, inside the *edit* dialog -- three taps deep, in a form about
 * renaming the room. The moment you are actually looking at a room's slots is the moment
 * you want to change which ones they are, so the control belongs at the end of that list.
 * The overflow menu still offers it, for a room you have not expanded.
 */
@Composable
internal fun ManageSlotsRow(hasTrackedSlots: Boolean, onClick: () -> Unit) {
    val metrics = LocalLayoutMetrics.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(
                start = metrics.slotIndent,
                end = 16.dp,
                top = metrics.slotRowVertical,
                bottom = metrics.slotRowVertical + 2.dp
            ),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = Icons.Default.Tune,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(18.dp)
        )
        Spacer(Modifier.width(8.dp))
        Text(
            // A room with nothing tracked yet is the one that most needs pointing at this,
            // and "Manage" understates the job when there is nothing to manage.
            text = if (hasTrackedSlots) "Manage slots" else "Choose slots to track",
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.primary
        )
    }
}

@Composable
fun SlotRow(
    slot: TrackedSlotDetail,
    /** Finished under the user's own definition, not merely goaled. */
    isFinished: Boolean,
    onClick: () -> Unit
) {
    val isDark = isSystemInDarkTheme()
    val finishedColor = if (isDark) Color(0xFF81C784) else Color(0xFF0E8A0E)
    val metrics = LocalLayoutMetrics.current

    // A flat row rather than a card. These now render *inside* the room card on the
    // rooms list, and a card nested in a card reads as two competing surfaces; the
    // indent and the divider carry the "belongs to this room" relationship instead.
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(
                start = metrics.slotIndent,
                end = 16.dp,
                top = metrics.slotRowVertical,
                bottom = metrics.slotRowVertical
            ),
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
                // Only Watching is marked, never Playing. Play is the default for every
                // slot and the only mode a user who is not on Cheese Tracker ever has, so
                // a "playing" badge would sit on every row of most people's screens and
                // tell them nothing. Marking the exception is what carries information.
                //
                // Gated on the Cheese state being present, not just on the mode: watch
                // mode's entire effect is on Cheese claiming, so without a linked tracker
                // a stored "watch" describes nothing the user can currently see. This is
                // the same condition SlotDetailScreen's "Watching" badge lives behind.
                if (slot.track_mode == TrackMode.WATCH && slot.cheese != null) {
                    Icon(
                        imageVector = Icons.Filled.Visibility,
                        contentDescription = "Watching, not claimed on Cheese Tracker",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(16.dp)
                    )
                    Spacer(Modifier.width(4.dp))
                }
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
                    color = if (isFinished) finishedColor else Color.Unspecified,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }

            // Game and last activity share a line. They were a line each, which made a
            // slot four lines tall for four short facts -- the row was long because of
            // how the facts were stacked, not because of how many there were. Both are
            // secondary detail at the same weight, so they read as one line of context.
            val subtitle = listOfNotNull(
                slot.game?.takeIf { it.isNotBlank() },
                slot.last_activity?.let { formatRelativeTime(it) }
            ).joinToString(" · ")
            if (subtitle.isNotEmpty()) {
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }

        // Check progress moved out of the stack and into its own trailing column, which
        // buys back a line and puts the numbers in a column you can scan straight down
        // to compare slots. The word "checks" is dropped rather than the numbers: the
        // fraction is the part people read, and the label is restored for screen readers
        // through contentDescription.
        val checksDone = slot.checks_done
        val totalLocations = slot.total_locations
        if (checksDone != null && totalLocations != null && totalLocations > 0) {
            Spacer(Modifier.width(8.dp))
            Text(
                text = "$checksDone/$totalLocations",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                modifier = Modifier.semantics {
                    contentDescription = "$checksDone of $totalLocations checks"
                }
            )
        }

        Spacer(Modifier.width(4.dp))
        Icon(
            imageVector = Icons.Default.ChevronRight,
            contentDescription = "View Details",
            tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
        )
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
