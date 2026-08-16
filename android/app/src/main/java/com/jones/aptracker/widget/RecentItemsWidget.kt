package com.jones.aptracker.widget

import android.appwidget.AppWidgetManager
import android.content.Context
import android.util.Log
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import androidx.compose.ui.graphics.Color
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.GlanceTheme
import androidx.glance.currentState
import androidx.glance.Image
import androidx.glance.ImageProvider
import androidx.glance.LocalSize
import androidx.glance.action.ActionParameters
import androidx.glance.action.actionParametersOf
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetManager
import androidx.glance.appwidget.SizeMode
import androidx.glance.appwidget.action.ActionCallback
import androidx.glance.appwidget.action.actionRunCallback
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.lazy.LazyColumn
import androidx.glance.appwidget.lazy.items
import androidx.glance.appwidget.provideContent
import androidx.glance.background
import androidx.glance.layout.Alignment
import androidx.glance.layout.Box
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.layout.size
import androidx.glance.layout.width
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.jones.aptracker.MainActivity
import com.jones.aptracker.R
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.network.HistoryItemEntity
import com.jones.aptracker.repository.HistorySyncWorker
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

data class RecentItemsWidgetState(
    val items: List<HistoryItemEntity> = emptyList(),
    val roomNames: Map<Int, String> = emptyMap(),
    val targetRoomId: Int = -1,
    val customTitle: String? = null,
    val isCompact: Boolean = false,
    val isLoading: Boolean = false,
    val isConfigured: Boolean = false
)

class RecentItemsWidget : GlanceAppWidget() {

    companion object {
        private val SMALL_SIZE = DpSize(120.dp, 100.dp)
        private val MEDIUM_SIZE = DpSize(220.dp, 120.dp)
        private val LARGE_SIZE = DpSize(260.dp, 200.dp)

        val COLOR_PROGRESSION = Color(0xFFD0BCFF)
        val COLOR_USEFUL = Color(0xFF69C4FF)
        val COLOR_TRAP = Color(0xFFFFB4AB)
        val COLOR_NORMAL = Color(0xFF8E9199)

        // Bumped by the config activity and the updater to force a running session to
        // re-read SharedPreferences and the database. See the comment in provideGlance.
        val REFRESH_TOKEN = longPreferencesKey("refresh_token")
    }

    override val sizeMode: SizeMode = SizeMode.Responsive(
        setOf(SMALL_SIZE, MEDIUM_SIZE, LARGE_SIZE)
    )

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val widgetId = try {
            GlanceAppWidgetManager(context).getAppWidgetId(id)
        } catch (e: Exception) {
            AppWidgetManager.INVALID_APPWIDGET_ID
        }

        val initialState = loadWidgetState(context, widgetId)

        provideContent {
            // Glance does NOT re-run provideGlance for a session that is already running. update()
            // only re-reads `stateDefinition` and recomposes the content lambda, so anything
            // captured before provideContent stays frozen for the life of that session -- which is
            // why a widget configured moments after placement kept rendering its pre-config state.
            // Reading the refresh token inside the composition and reloading when it changes is
            // what makes update() actually pick up new configuration and new history rows.
            val refreshToken = currentState<Preferences>()[REFRESH_TOKEN] ?: 0L
            var widgetState by remember { mutableStateOf(initialState) }
            LaunchedEffect(refreshToken) {
                widgetState = loadWidgetState(context, widgetId)
            }

            GlanceTheme {
                val size = LocalSize.current

                val openActivityAction = actionStartActivity<MainActivity>(
                    if (widgetState.targetRoomId != -1) {
                        actionParametersOf(
                            ActionParameters.Key<String>("target_tab") to "activity",
                            ActionParameters.Key<Int>("target_room_id") to widgetState.targetRoomId
                        )
                    } else {
                        actionParametersOf(
                            ActionParameters.Key<String>("target_tab") to "activity"
                        )
                    }
                )

                Box(
                    modifier = GlanceModifier
                        .fillMaxSize()
                        .background(GlanceTheme.colors.surface)
                        .cornerRadius(16.dp)
                        .padding(if (size.width < 160.dp) 10.dp else 14.dp)
                ) {
                    when {
                        !widgetState.isConfigured -> {
                            SetupWidgetLayout(onClick = openActivityAction)
                        }
                        size.height < 110.dp -> {
                            SmallWidgetLayout(
                                item = widgetState.items.firstOrNull(),
                                roomNames = widgetState.roomNames,
                                title = widgetState.customTitle ?: "Archipelago Alerts",
                                isCompact = widgetState.isCompact || size.width < 160.dp,
                                onClick = openActivityAction
                            )
                        }
                        else -> {
                            StandardWidgetLayout(
                                items = widgetState.items,
                                roomNames = widgetState.roomNames,
                                title = widgetState.customTitle ?: "Archipelago Alerts",
                                isCompact = widgetState.isCompact || size.width < 180.dp,
                                isLoading = widgetState.isLoading,
                                onOpenApp = openActivityAction
                            )
                        }
                    }
                }
            }
        }
    }
}

private suspend fun loadWidgetState(context: Context, widgetId: Int): RecentItemsWidgetState =
    withContext(Dispatchers.IO) {
        val database = AppDatabase.getInstance(context)
        val prefs = context.getSharedPreferences("ap_tracker_prefs", Context.MODE_PRIVATE)

        val widgetPrefs = if (widgetId != AppWidgetManager.INVALID_APPWIDGET_ID) {
            context.getSharedPreferences("widget_${widgetId}_prefs", Context.MODE_PRIVATE)
        } else null

        // Guard: never render "all rooms / standard" defaults for a widget that hasn't been
        // configured yet. Without this, a composition that races ahead of the config activity
        // (or a widget whose prefs were cleared) shows a plausible-but-wrong feed instead of a
        // neutral setup prompt.
        val isConfigured = widgetPrefs?.getBoolean("is_configured", false) ?: false
        if (!isConfigured) {
            return@withContext RecentItemsWidgetState(isConfigured = false)
        }

        val targetRoomId = widgetPrefs?.getInt("target_room_id", -1) ?: -1
        val fontDensity = widgetPrefs?.getString("font_density", "standard") ?: "standard"
        val isCompactConfig = fontDensity == "compact"

        val showProgression = prefs.getBoolean("ui_show_progression", true)
        val showUseful = prefs.getBoolean("ui_show_useful", true)
        val showFiller = prefs.getBoolean("ui_show_filler", false)
        val showTrap = prefs.getBoolean("ui_show_trap", false)
        val showFinished = prefs.getBoolean("ui_show_finished", true)
        val showIgnoredItems = prefs.getBoolean("ui_show_ignored_items", false)

        val rooms = try {
            database.roomDao().getAllRoomsOneShot()
        } catch (e: Exception) {
            emptyList()
        }
        val roomNames = rooms.associate { it.id to it.alias }
        val activeRoomIds = rooms.filter { !it.is_archived }.map { it.id }.toSet()

        // Room-Specific Query Optimization: If widget is configured for a specific room,
        // query that room's history directly from SQLite rather than the global scan window.
        val rawHistoryItems = try {
            if (targetRoomId != -1) {
                database.historyDao().getHistoryForRoomPaged(roomId = targetRoomId, limit = 200, offset = 0)
            } else {
                database.historyDao().getGlobalHistoryPaged(limit = 500, offset = 0)
            }
        } catch (e: Exception) {
            Log.e("RecentItemsWidget", "Failed to fetch history items from DB", e)
            emptyList()
        }

        val filteredItems = rawHistoryItems.filter { item ->
            val matchesRoom = if (targetRoomId != -1) {
                item.roomId == targetRoomId
            } else {
                item.roomId == null || activeRoomIds.isEmpty() || item.roomId in activeRoomIds
            }
            // Architectural note: Standalone widget uses item.isPlayerFinished stored in SQLite;
            // the full in-app feed derives finished status from live slot data (HistoryScreen.kt:990).
            val matchesFinished = showFinished || !item.isPlayerFinished

            // --- TYPE CHECK (Prioritized to match visual colors and in-app feed verbatim) ---
            val isProgression = (item.itemFlags and 1) != 0
            val isUseful = (item.itemFlags and 2) != 0
            val isTrap = (item.itemFlags and 4) != 0

            val matchesType = when {
                isProgression -> showProgression
                isUseful -> showUseful
                isTrap -> showTrap
                else -> showFiller
            }

            // Whitelist exempts items from both category and ignored filters
            val matchesCategoryOrWhitelist = item.isWhitelisted || matchesType
            val matchesIgnoredOrWhitelist = item.isWhitelisted || (showIgnoredItems || !item.isIgnored)

            matchesRoom && matchesFinished && matchesCategoryOrWhitelist && matchesIgnoredOrWhitelist
        }.take(10)

        val targetRoomName = if (targetRoomId != -1) roomNames[targetRoomId] else null

        RecentItemsWidgetState(
            items = filteredItems,
            roomNames = roomNames,
            targetRoomId = targetRoomId,
            customTitle = targetRoomName,
            isCompact = isCompactConfig,
            isLoading = false,
            isConfigured = true
        )
    }

@Composable
private fun SetupWidgetLayout(onClick: androidx.glance.action.Action) {
    Box(
        modifier = GlanceModifier
            .fillMaxSize()
            .clickable(onClick),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = "Setup needed",
                style = TextStyle(
                    color = GlanceTheme.colors.primary,
                    fontWeight = FontWeight.Bold,
                    fontSize = 14.sp
                ),
                maxLines = 1
            )
            Spacer(modifier = GlanceModifier.height(4.dp))
            Text(
                text = "Tap to open the app",
                style = TextStyle(
                    color = GlanceTheme.colors.onSurfaceVariant,
                    fontSize = 12.5.sp
                ),
                maxLines = 1
            )
        }
    }
}

@Composable
private fun SmallWidgetLayout(
    item: HistoryItemEntity?,
    roomNames: Map<Int, String>,
    title: String,
    isCompact: Boolean,
    onClick: androidx.glance.action.Action
) {
    Column(
        modifier = GlanceModifier
            .fillMaxSize()
            .clickable(onClick),
        verticalAlignment = Alignment.CenterVertically,
        horizontalAlignment = Alignment.Start
    ) {
        Row(
            modifier = GlanceModifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = title,
                style = TextStyle(
                    color = GlanceTheme.colors.primary,
                    fontWeight = FontWeight.Bold,
                    fontSize = if (isCompact) 12.sp else 13.5.sp
                ),
                maxLines = 1,
                modifier = GlanceModifier.defaultWeight()
            )
            Image(
                provider = ImageProvider(R.drawable.ic_widget_refresh),
                contentDescription = "Refresh",
                modifier = GlanceModifier
                    .size(18.dp)
                    .clickable(actionRunCallback<RefreshRecentItemsAction>())
            )
        }

        Spacer(modifier = GlanceModifier.height(if (isCompact) 4.dp else 6.dp))

        if (item == null) {
            Text(
                text = "No recent items",
                style = TextStyle(
                    color = GlanceTheme.colors.onSurfaceVariant,
                    fontSize = if (isCompact) 11.5.sp else 13.sp
                )
            )
        } else {
            val itemColor = getItemColor(item.itemFlags)
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = GlanceModifier.fillMaxWidth()
            ) {
                Box(
                    modifier = GlanceModifier
                        .size(if (isCompact) 7.5.dp else 9.dp)
                        .cornerRadius(if (isCompact) 3.75.dp else 4.5.dp)
                        .background(itemColor)
                ) {}
                Spacer(modifier = GlanceModifier.width(6.dp))
                Text(
                    text = item.itemName,
                    style = TextStyle(
                        color = GlanceTheme.colors.onSurface,
                        fontWeight = FontWeight.Bold,
                        fontSize = if (isCompact) 13.5.sp else 15.sp
                    ),
                    maxLines = 1
                )
            }

            Spacer(modifier = GlanceModifier.height(2.dp))

            val receiverName = item.playerAlias?.takeIf { it.isNotBlank() } ?: item.playerName
            val roomAlias = if (title == "Archipelago Alerts") item.roomId?.let { roomNames[it] } else null
            val timeAgo = formatRelativeTimestamp(item.timestamp)
            val detailsText = listOfNotNull("To $receiverName", roomAlias, timeAgo).joinToString(" • ")

            Text(
                text = detailsText,
                style = TextStyle(
                    color = GlanceTheme.colors.onSurfaceVariant,
                    fontSize = if (isCompact) 11.sp else 12.5.sp
                ),
                maxLines = 1
            )
        }
    }
}

@Composable
private fun StandardWidgetLayout(
    items: List<HistoryItemEntity>,
    roomNames: Map<Int, String>,
    title: String,
    isCompact: Boolean,
    isLoading: Boolean,
    onOpenApp: androidx.glance.action.Action
) {
    Column(
        modifier = GlanceModifier.fillMaxSize()
    ) {
        // Header with Archipelago Alerts / Room branding + Subtitle
        Row(
            modifier = GlanceModifier
                .fillMaxWidth()
                .padding(bottom = if (isCompact) 4.dp else 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(
                modifier = GlanceModifier
                    .defaultWeight()
                    .clickable(onOpenApp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        text = title,
                        style = TextStyle(
                            color = GlanceTheme.colors.primary,
                            fontWeight = FontWeight.Bold,
                            fontSize = if (isCompact) 13.5.sp else 15.sp
                        ),
                        maxLines = 1
                    )
                    Text(
                        text = if (title != "Archipelago Alerts") "Archipelago Alerts • Recent Items" else "Recent Items",
                        style = TextStyle(
                            color = GlanceTheme.colors.onSurfaceVariant,
                            fontWeight = FontWeight.Medium,
                            fontSize = if (isCompact) 10.5.sp else 11.5.sp
                        ),
                        maxLines = 1
                    )
                }
            }

            Image(
                provider = ImageProvider(R.drawable.ic_widget_refresh),
                contentDescription = "Refresh",
                modifier = GlanceModifier
                    .size(if (isCompact) 18.dp else 20.dp)
                    .clickable(actionRunCallback<RefreshRecentItemsAction>())
            )
        }

        if (items.isEmpty()) {
            Box(
                modifier = GlanceModifier
                    .fillMaxSize()
                    .clickable(onOpenApp),
                contentAlignment = Alignment.Center
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        text = if (isLoading) "Loading items..." else "No recent items received",
                        style = TextStyle(
                            color = GlanceTheme.colors.onSurface,
                            fontSize = if (isCompact) 12.5.sp else 14.sp,
                            fontWeight = FontWeight.Bold
                        )
                    )
                    Spacer(modifier = GlanceModifier.height(4.dp))
                    Text(
                        text = "Tap to check filters or active rooms",
                        style = TextStyle(
                            color = GlanceTheme.colors.onSurfaceVariant,
                            fontSize = if (isCompact) 11.sp else 12.5.sp
                        )
                    )
                }
            }
        } else {
            LazyColumn(
                modifier = GlanceModifier.fillMaxSize()
            ) {
                items(items) { item ->
                    ItemRow(
                        item = item,
                        roomNames = roomNames,
                        showRoomAlias = title == "Archipelago Alerts",
                        isCompact = isCompact,
                        onClick = onOpenApp
                    )
                }
            }
        }
    }
}

@Composable
private fun ItemRow(
    item: HistoryItemEntity,
    roomNames: Map<Int, String>,
    showRoomAlias: Boolean,
    isCompact: Boolean,
    onClick: androidx.glance.action.Action
) {
    val itemColor = getItemColor(item.itemFlags)
    val receiverName = item.playerAlias?.takeIf { it.isNotBlank() } ?: item.playerName
    val senderName = item.senderAlias?.takeIf { it.isNotBlank() } ?: item.senderName ?: "Server"
    val timeAgo = formatRelativeTimestamp(item.timestamp)
    val roomAlias = if (showRoomAlias) (item.roomId?.let { roomNames[it] } ?: item.receivingGame ?: "") else ""

    Column(
        modifier = GlanceModifier
            .fillMaxWidth()
            .padding(vertical = if (isCompact) 2.5.dp else 4.5.dp)
            .clickable(onClick)
    ) {
        Row(
            modifier = GlanceModifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = GlanceModifier
                    .size(if (isCompact) 7.5.dp else 9.dp)
                    .cornerRadius(if (isCompact) 3.75.dp else 4.5.dp)
                    .background(itemColor)
            ) {}

            Spacer(modifier = GlanceModifier.width(if (isCompact) 6.dp else 8.dp))

            Text(
                text = item.itemName,
                style = TextStyle(
                    color = GlanceTheme.colors.onSurface,
                    fontWeight = FontWeight.Bold,
                    fontSize = if (isCompact) 13.sp else 14.5.sp
                ),
                maxLines = 1,
                modifier = GlanceModifier.defaultWeight()
            )

            Spacer(modifier = GlanceModifier.width(4.dp))

            Text(
                text = timeAgo,
                style = TextStyle(
                    color = GlanceTheme.colors.onSurfaceVariant,
                    fontSize = if (isCompact) 10.5.sp else 12.sp
                )
            )
        }

        Row(
            modifier = GlanceModifier
                .fillMaxWidth()
                .padding(start = if (isCompact) 13.5.dp else 17.dp, top = if (isCompact) 1.dp else 2.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val detailsText = buildString {
                append("To: ")
                append(receiverName)
                append(" (from ")
                append(senderName)
                append(")")
                if (roomAlias.isNotBlank()) {
                    append(" • ")
                    append(roomAlias)
                }
            }

            Text(
                text = detailsText,
                style = TextStyle(
                    color = GlanceTheme.colors.onSurfaceVariant,
                    fontSize = if (isCompact) 10.5.sp else 12.sp
                ),
                maxLines = 1
            )
        }
    }
}

private fun getItemColor(itemFlags: Int): Color {
    return when {
        (itemFlags and 1) != 0 -> RecentItemsWidget.COLOR_PROGRESSION
        (itemFlags and 2) != 0 -> RecentItemsWidget.COLOR_USEFUL
        (itemFlags and 4) != 0 -> RecentItemsWidget.COLOR_TRAP
        else -> RecentItemsWidget.COLOR_NORMAL
    }
}

fun formatRelativeTimestamp(isoString: String): String {
    return try {
        var clean = isoString.trim()
        if (clean.contains(" ")) {
            clean = clean.replace(" ", "T")
        }
        val hasTimeZone = clean.endsWith("Z") || (clean.indexOfAny(charArrayOf('+', '-'), 10) != -1)
        if (!hasTimeZone) {
            clean += "Z"
        }
        val itemTime = Instant.parse(clean)
        val now = Instant.now()
        val duration = Duration.between(itemTime, now)
        val seconds = duration.seconds

        when {
            seconds < 60 -> "just now"
            seconds < 3600 -> "${seconds / 60}m ago"
            seconds < 86400 -> "${seconds / 3600}h ago"
            seconds < 604800 -> "${seconds / 86400}d ago"
            else -> itemTime.atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("MMM d"))
        }
    } catch (e: Exception) {
        "recently"
    }
}

class RefreshRecentItemsAction : ActionCallback {
    override suspend fun onAction(
        context: Context,
        glanceId: GlanceId,
        parameters: ActionParameters
    ) {
        try {
            val syncRequest = OneTimeWorkRequestBuilder<HistorySyncWorker>().build()
            WorkManager.getInstance(context).enqueue(syncRequest)
        } catch (e: Exception) {
            Log.e("RecentItemsWidget", "Failed to enqueue background sync from widget refresh", e)
        }
        // Goes through the updater so the refresh token is bumped first; calling update()
        // directly would only recompose this session's already-loaded state.
        RecentItemsWidgetUpdater.update(context)
    }
}
