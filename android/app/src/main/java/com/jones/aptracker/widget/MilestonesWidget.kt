package com.jones.aptracker.widget

import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.SharedPreferences
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.GlanceTheme
import androidx.glance.Image
import androidx.glance.ImageProvider
import androidx.glance.LocalSize
import androidx.glance.action.ActionParameters
import androidx.glance.action.actionParametersOf
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetManager
import androidx.glance.appwidget.LinearProgressIndicator
import androidx.glance.appwidget.SizeMode
import androidx.glance.appwidget.action.ActionCallback
import androidx.glance.appwidget.action.actionRunCallback
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.lazy.LazyColumn
import androidx.glance.appwidget.lazy.items
import androidx.glance.appwidget.provideContent
import androidx.glance.background
import androidx.glance.currentState
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
import androidx.glance.text.TextAlign
import androidx.glance.text.TextStyle
import androidx.glance.unit.ColorProvider
import com.jones.aptracker.MainActivity
import com.jones.aptracker.R
import com.jones.aptracker.repository.MilestoneGroupDisplay
import com.jones.aptracker.repository.MilestoneItemProgress
import com.jones.aptracker.repository.MilestonesRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

data class MilestonesWidgetState(
    val groups: List<MilestoneGroupDisplay> = emptyList(),
    val targetRoomId: Int = -1,
    val roomAlias: String? = null,
    val customTitle: String? = null,
    val isAllRooms: Boolean = false,
    val slotCount: Int = 0,
    val isCompact: Boolean = false,
    /** When false, milestone rows drop the leading flag emoji. */
    val showFlagEmoji: Boolean = true,
    /** True until the composition's first data load finishes. */
    val isLoading: Boolean = false,
    /** False until the sync layer has populated the milestone cache at least once. */
    val hasCachedData: Boolean = false,
    val isConfigured: Boolean = false
)

class MilestonesWidget : GlanceAppWidget() {

    companion object {
        private val SMALL_SIZE = DpSize(120.dp, 100.dp)
        private val MEDIUM_SIZE = DpSize(220.dp, 120.dp)
        private val LARGE_SIZE = DpSize(260.dp, 200.dp)

        val COLOR_SUCCESS = Color(0xFF80D992)
        val COLOR_TRACK = Color(0xFF3B383E)
        val COLOR_PROGRESSION = Color(0xFFD0BCFF)

        // Bumped by the config activity and the updater to force a running session to
        // re-read SharedPreferences and the database, preventing stale widget states.
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

        // Only the configuration is read out here, and only from SharedPreferences. It decides
        // whether to show the setup prompt, which has to be right on the very first frame.
        //
        // Milestone data is loaded inside the composition instead. Glance does NOT re-run
        // provideGlance for a session that is already running -- update() only re-reads
        // `stateDefinition` and recomposes the content lambda -- so anything captured here stays
        // frozen for the life of that session. Reading the refresh token inside the composition
        // and reloading when it changes is what makes update() pick up new configuration and
        // newly synced items.
        val config = loadWidgetConfig(context, widgetId)

        provideContent {
            val refreshToken = currentState<Preferences>()[REFRESH_TOKEN] ?: 0L
            var widgetState by remember { mutableStateOf(config) }
            LaunchedEffect(refreshToken) {
                widgetState = loadWidgetState(context, widgetId)
            }

            GlanceTheme {
                val size = LocalSize.current

                val openRoomAction = actionStartActivity<MainActivity>(
                    if (widgetState.targetRoomId != -1) {
                        actionParametersOf(
                            ActionParameters.Key<String>("target_tab") to "rooms",
                            ActionParameters.Key<Int>("target_room_id") to widgetState.targetRoomId
                        )
                    } else {
                        actionParametersOf(
                            ActionParameters.Key<String>("target_tab") to "rooms"
                        )
                    }
                )

                val placeholderTitle = widgetState.customTitle
                    ?: if (widgetState.isAllRooms) "All Rooms" else (widgetState.roomAlias ?: "Milestones")

                Box(
                    modifier = GlanceModifier
                        .fillMaxSize()
                        .background(GlanceTheme.colors.surface)
                        .cornerRadius(16.dp)
                        .padding(if (size.width < 160.dp) 10.dp else 14.dp)
                ) {
                    when {
                        !widgetState.isConfigured -> {
                            SetupMilestonesLayout(onClick = openRoomAction)
                        }
                        // Configured, but there is nothing to draw yet: either the composition's
                        // load is still in flight, or the app has not completed a sync. Showing the
                        // setup prompt here is what made a just-configured widget look broken.
                        widgetState.isLoading || !widgetState.hasCachedData -> {
                            LoadingMilestonesLayout(
                                title = placeholderTitle,
                                onClick = openRoomAction
                            )
                        }
                        widgetState.groups.isEmpty() -> {
                            EmptyMilestonesLayout(
                                title = placeholderTitle,
                                onClick = openRoomAction
                            )
                        }
                        size.height < 110.dp -> {
                            SmallMilestonesLayout(
                                state = widgetState,
                                isCompact = widgetState.isCompact || size.width < 160.dp,
                                onOpenRoom = openRoomAction
                            )
                        }
                        else -> {
                            StandardMilestonesLayout(
                                state = widgetState,
                                isCompact = widgetState.isCompact || size.width < 180.dp,
                                isLarge = size.height >= 180.dp,
                                onOpenRoom = openRoomAction
                            )
                        }
                    }
                }
            }
        }
    }
}

/**
 * Reads just this widget's configuration. Cheap enough to run before the first frame.
 */
private suspend fun loadWidgetConfig(context: Context, widgetId: Int): MilestonesWidgetState =
    withContext(Dispatchers.IO) {
        val widgetPrefs = if (widgetId != AppWidgetManager.INVALID_APPWIDGET_ID) {
            context.getSharedPreferences("widget_${widgetId}_prefs", Context.MODE_PRIVATE)
        } else null

        // Guard: never render defaults for a widget that hasn't been configured yet. Without this,
        // a composition that races ahead of the config activity shows a plausible-but-wrong scope
        // instead of a neutral setup prompt.
        val isConfigured = widgetPrefs?.getBoolean("is_configured", false) ?: false
        if (widgetPrefs == null || !isConfigured) {
            return@withContext MilestonesWidgetState(isConfigured = false)
        }

        purgeLegacyNetworkCache(widgetPrefs)

        val targetRoomId = widgetPrefs.getInt("target_room_id", -1)
        val isAllRooms = targetRoomId == -1

        MilestonesWidgetState(
            targetRoomId = targetRoomId,
            roomAlias = if (isAllRooms) "All Rooms" else (widgetPrefs.getString("room_alias", null) ?: "Milestones"),
            customTitle = widgetPrefs.getString("custom_title", null),
            isAllRooms = isAllRooms,
            isCompact = (widgetPrefs.getString("font_density", "standard") ?: "standard") == "compact",
            showFlagEmoji = widgetPrefs.getBoolean("show_flag_emoji", true),
            isLoading = true,
            isConfigured = true
        )
    }

/**
 * Full widget state: configuration plus milestone progress read from the local cache.
 *
 * This is local-only by design. See [MilestonesRepository] for why the network fetches moved to
 * the sync layer.
 */
private suspend fun loadWidgetState(context: Context, widgetId: Int): MilestonesWidgetState {
    val config = loadWidgetConfig(context, widgetId)
    if (!config.isConfigured) return config

    val snapshot = MilestonesRepository.loadSnapshot(context, config.targetRoomId)
    return config.copy(
        groups = snapshot.groups,
        slotCount = snapshot.slotCount,
        hasCachedData = snapshot.hasCache,
        isLoading = false
    )
}

/**
 * Drops the JSON blobs the widget used to write back when it fetched from the network itself.
 * On a busy account these grew past 1 MB, and SharedPreferences loads the entire file into memory
 * on first access and rewrites all of it on every apply().
 */
private fun purgeLegacyNetworkCache(prefs: SharedPreferences) {
    val staleKeys = prefs.all.keys.filter {
        it == "cached_all_tracked_slots" || it.startsWith("cached_threshold_groups_")
    }
    if (staleKeys.isEmpty()) return

    prefs.edit().apply { staleKeys.forEach { remove(it) } }.apply()
}

/**
 * The widget's refresh button. This is the one widget-side path allowed to hit the network: it is
 * explicitly user-initiated, so the round trip is expected rather than a surprise.
 */
class RefreshMilestonesAction : ActionCallback {
    override suspend fun onAction(
        context: Context,
        glanceId: GlanceId,
        parameters: ActionParameters
    ) {
        MilestonesRepository.refreshCache(context)
        MilestonesWidgetUpdater.update(context)
    }
}

@Composable
private fun SetupMilestonesLayout(onClick: androidx.glance.action.Action) {
    Column(
        modifier = GlanceModifier
            .fillMaxSize()
            .clickable(onClick),
        verticalAlignment = Alignment.CenterVertically,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = "🚩 Setup Milestones",
            style = TextStyle(
                color = GlanceTheme.colors.primary,
                fontWeight = FontWeight.Bold,
                fontSize = 14.sp
            )
        )
        Spacer(modifier = GlanceModifier.height(4.dp))
        Text(
            text = "Tap to select your Room or All Active Rooms.",
            style = TextStyle(
                color = GlanceTheme.colors.onSurfaceVariant,
                fontSize = 12.sp,
                textAlign = TextAlign.Center
            )
        )
    }
}

/**
 * Shown when the widget is configured but has no data to draw yet -- during the composition's
 * first load, or before the app's first sync has populated the milestone cache. Distinct from
 * [SetupMilestonesLayout], which means the user has not chosen a room scope at all.
 */
@Composable
private fun LoadingMilestonesLayout(
    title: String,
    onClick: androidx.glance.action.Action
) {
    Column(
        modifier = GlanceModifier
            .fillMaxSize()
            .clickable(onClick),
        verticalAlignment = Alignment.CenterVertically,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = title,
            style = TextStyle(
                color = GlanceTheme.colors.primary,
                fontWeight = FontWeight.Bold,
                fontSize = 14.sp
            ),
            maxLines = 1
        )
        Spacer(modifier = GlanceModifier.height(4.dp))
        Text(
            text = "Loading milestones…",
            style = TextStyle(
                color = GlanceTheme.colors.onSurfaceVariant,
                fontSize = 12.sp,
                textAlign = TextAlign.Center
            )
        )
    }
}

@Composable
private fun EmptyMilestonesLayout(
    title: String,
    onClick: androidx.glance.action.Action
) {
    Column(
        modifier = GlanceModifier
            .fillMaxSize()
            .clickable(onClick),
        verticalAlignment = Alignment.CenterVertically,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = title,
            style = TextStyle(
                color = GlanceTheme.colors.primary,
                fontWeight = FontWeight.Bold,
                fontSize = 14.sp
            ),
            maxLines = 1
        )
        Spacer(modifier = GlanceModifier.height(4.dp))
        Text(
            text = "No milestone groups found in your tracked rooms. Tap to view your slots.",
            style = TextStyle(
                color = GlanceTheme.colors.onSurfaceVariant,
                fontSize = 11.5.sp,
                textAlign = TextAlign.Center
            )
        )
    }
}

@Composable
private fun SmallMilestonesLayout(
    state: MilestonesWidgetState,
    isCompact: Boolean,
    onOpenRoom: androidx.glance.action.Action
) {
    // Focus on nearest incomplete milestone group, or first group
    val targetGroup = state.groups.firstOrNull { !it.isComplete } ?: state.groups.firstOrNull()

    val openSlotAction = if (targetGroup != null) {
        actionStartActivity<MainActivity>(
            actionParametersOf(
                ActionParameters.Key<String>("target_tab") to "rooms",
                ActionParameters.Key<Int>("target_room_id") to targetGroup.roomDbId,
                ActionParameters.Key<Int>("target_slot_id") to targetGroup.slotId
            )
        )
    } else {
        onOpenRoom
    }

    Column(
        modifier = GlanceModifier
            .fillMaxSize()
            .clickable(openSlotAction),
        verticalAlignment = Alignment.CenterVertically,
        horizontalAlignment = Alignment.Start
    ) {
        // Header
        Row(
            modifier = GlanceModifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val titleText = state.customTitle
                ?: if (state.isAllRooms) "Archipelago Alerts" else (state.roomAlias ?: "Milestones")

            Text(
                text = titleText,
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
                    .clickable(actionRunCallback<RefreshMilestonesAction>())
            )
        }

        Spacer(modifier = GlanceModifier.height(if (isCompact) 3.dp else 5.dp))

        if (targetGroup != null) {
            val flag = if (state.showFlagEmoji) "🚩 " else ""
            val groupLabel = when {
                state.isAllRooms || state.slotCount > 1 -> "$flag${targetGroup.name} (${targetGroup.slotName})"
                else -> "$flag${targetGroup.name}"
            }

            Row(
                modifier = GlanceModifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = groupLabel,
                    style = TextStyle(
                        color = GlanceTheme.colors.onSurface,
                        fontWeight = FontWeight.Bold,
                        fontSize = if (isCompact) 12.sp else 13.5.sp
                    ),
                    maxLines = 1,
                    modifier = GlanceModifier.defaultWeight()
                )
                Spacer(modifier = GlanceModifier.width(4.dp))
                Text(
                    text = when {
                        targetGroup.isComplete -> "✓ Complete"
                        targetGroup.isServerTracked -> "Tracked on server"
                        else -> "${targetGroup.totalAcquired}/${targetGroup.totalRequired}"
                    },
                    style = TextStyle(
                        color = if (targetGroup.isComplete) ColorProvider(MilestonesWidget.COLOR_SUCCESS) else GlanceTheme.colors.primary,
                        fontWeight = FontWeight.Bold,
                        fontSize = if (isCompact) 11.sp else 12.sp
                    )
                )
            }

            Spacer(modifier = GlanceModifier.height(4.dp))

            LinearProgressIndicator(
                progress = targetGroup.progressRatio,
                modifier = GlanceModifier
                    .fillMaxWidth()
                    .height(if (isCompact) 4.dp else 6.dp)
                    .cornerRadius(if (isCompact) 2.dp else 3.dp),
                color = if (targetGroup.isComplete) ColorProvider(MilestonesWidget.COLOR_SUCCESS) else GlanceTheme.colors.primary,
                backgroundColor = ColorProvider(MilestonesWidget.COLOR_TRACK)
            )

            Spacer(modifier = GlanceModifier.height(2.dp))

            val itemsSummary = targetGroup.items.joinToString(" • ") { formatItemProgress(it) }
            Text(
                text = itemsSummary,
                style = TextStyle(
                    color = GlanceTheme.colors.onSurfaceVariant,
                    fontSize = if (isCompact) 10.sp else 11.5.sp
                ),
                maxLines = 1
            )
        }
    }
}

@Composable
private fun StandardMilestonesLayout(
    state: MilestonesWidgetState,
    isCompact: Boolean,
    isLarge: Boolean,
    onOpenRoom: androidx.glance.action.Action
) {
    val completedCount = state.groups.count { it.isComplete }
    val totalCount = state.groups.size

    val titleText = state.customTitle
        ?: if (state.isAllRooms) "Archipelago Alerts" else (state.roomAlias ?: "Milestones")
    val subtitleText = if (state.isAllRooms) {
        "All Rooms • $completedCount of $totalCount Complete"
    } else {
        "Milestones • $completedCount of $totalCount Complete"
    }

    Column(
        modifier = GlanceModifier.fillMaxSize()
    ) {
        // Header
        Row(
            modifier = GlanceModifier
                .fillMaxWidth()
                .padding(bottom = if (isCompact) 4.dp else 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(
                modifier = GlanceModifier
                    .defaultWeight()
                    .clickable(onOpenRoom),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        text = titleText,
                        style = TextStyle(
                            color = GlanceTheme.colors.primary,
                            fontWeight = FontWeight.Bold,
                            fontSize = if (isCompact) 13.5.sp else 15.sp
                        ),
                        maxLines = 1
                    )
                    Text(
                        text = subtitleText,
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
                    .clickable(actionRunCallback<RefreshMilestonesAction>())
            )
        }

        if (isLarge) {
            LazyColumn(
                modifier = GlanceModifier.fillMaxSize()
            ) {
                items(state.groups) { group ->
                    val openSlotAction = actionStartActivity<MainActivity>(
                        actionParametersOf(
                            ActionParameters.Key<String>("target_tab") to "rooms",
                            ActionParameters.Key<Int>("target_room_id") to group.roomDbId,
                            ActionParameters.Key<Int>("target_slot_id") to group.slotId
                        )
                    )

                    MilestoneGroupRow(
                        group = group,
                        isAllRooms = state.isAllRooms,
                        showSlotName = state.isAllRooms || state.slotCount > 1,
                        showFlagEmoji = state.showFlagEmoji,
                        isCompact = isCompact,
                        onClick = openSlotAction,
                        modifier = GlanceModifier.padding(vertical = if (isCompact) 3.dp else 5.dp)
                    )
                }
            }
        } else {
            // Medium size: show top 2 or 3 groups in a column
            val displayGroups = state.groups.take(if (isCompact) 3 else 2)
            Column(
                modifier = GlanceModifier.fillMaxSize()
            ) {
                displayGroups.forEachIndexed { index, group ->
                    val openSlotAction = actionStartActivity<MainActivity>(
                        actionParametersOf(
                            ActionParameters.Key<String>("target_tab") to "rooms",
                            ActionParameters.Key<Int>("target_room_id") to group.roomDbId,
                            ActionParameters.Key<Int>("target_slot_id") to group.slotId
                        )
                    )

                    MilestoneGroupRow(
                        group = group,
                        isAllRooms = state.isAllRooms,
                        showSlotName = state.isAllRooms || state.slotCount > 1,
                        showFlagEmoji = state.showFlagEmoji,
                        isCompact = isCompact,
                        onClick = openSlotAction,
                        modifier = GlanceModifier.padding(vertical = if (isCompact) 2.dp else 4.dp)
                    )
                }
            }
        }
    }
}

/**
 * One requirement as "Name (2/3)".
 *
 * Item-group requirements are resolved server-side against the datapackage, so the client cannot
 * count them; those render as an em dash rather than a confident and wrong 0.
 */
private fun formatItemProgress(
    item: MilestoneItemProgress,
    showGroupSuffix: Boolean = false
): String {
    val suffix = if (showGroupSuffix && item.isGroup) " (Group)" else ""
    val progress = if (item.isIndeterminate) {
        "—"
    } else {
        "${item.quantityAcquired}/${item.quantityRequired}"
    }
    return "${item.itemName}$suffix ($progress)"
}

@Composable
private fun MilestoneGroupRow(
    group: MilestoneGroupDisplay,
    isAllRooms: Boolean,
    showSlotName: Boolean,
    showFlagEmoji: Boolean,
    isCompact: Boolean,
    onClick: androidx.glance.action.Action,
    modifier: GlanceModifier = GlanceModifier
) {
    val flag = if (showFlagEmoji) "🚩 " else ""
    val groupLabel = when {
        isAllRooms -> "$flag${group.name} • ${group.slotName} (${group.roomAlias})"
        showSlotName -> "$flag${group.name} • ${group.slotName}"
        else -> "$flag${group.name}"
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .clickable(onClick)
    ) {
        Row(
            modifier = GlanceModifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = groupLabel,
                style = TextStyle(
                    color = GlanceTheme.colors.onSurface,
                    fontWeight = FontWeight.Bold,
                    fontSize = if (isCompact) 12.5.sp else 13.5.sp
                ),
                maxLines = 1,
                modifier = GlanceModifier.defaultWeight()
            )
            Spacer(modifier = GlanceModifier.width(6.dp))
            val percent = (group.progressRatio * 100).toInt()
            val statusText = if (group.isServerTracked) {
                "Tracked on server"
            } else if (group.isComplete) {
                "✓ Complete"
            } else {
                "${group.totalAcquired}/${group.totalRequired} ($percent%)"
            }
            Text(
                text = statusText,
                style = TextStyle(
                    color = if (group.isComplete) ColorProvider(MilestonesWidget.COLOR_SUCCESS) else GlanceTheme.colors.primary,
                    fontWeight = FontWeight.Bold,
                    fontSize = if (isCompact) 11.sp else 12.sp
                )
            )
        }

        Spacer(modifier = GlanceModifier.height(3.dp))

        LinearProgressIndicator(
            progress = group.progressRatio,
            modifier = GlanceModifier
                .fillMaxWidth()
                .height(if (isCompact) 4.dp else 6.dp)
                .cornerRadius(if (isCompact) 2.dp else 3.dp),
            color = if (group.isComplete) ColorProvider(MilestonesWidget.COLOR_SUCCESS) else GlanceTheme.colors.primary,
            backgroundColor = ColorProvider(MilestonesWidget.COLOR_TRACK)
        )

        Spacer(modifier = GlanceModifier.height(2.dp))

        val itemsSummary = group.items.joinToString(" • ") { formatItemProgress(it, showGroupSuffix = true) }
        Text(
            text = itemsSummary,
            style = TextStyle(
                color = GlanceTheme.colors.onSurfaceVariant,
                fontSize = if (isCompact) 10.sp else 11.sp
            ),
            maxLines = 1
        )
    }
}
