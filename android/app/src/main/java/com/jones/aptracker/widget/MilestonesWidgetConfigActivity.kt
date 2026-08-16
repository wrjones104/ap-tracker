package com.jones.aptracker.widget

import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
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
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.ViewDay
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.edit
import androidx.glance.appwidget.GlanceAppWidgetManager
import androidx.glance.appwidget.state.updateAppWidgetState
import androidx.lifecycle.lifecycleScope
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.network.RoomEntity
import com.jones.aptracker.ui.theme.APTrackerTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
class MilestonesWidgetConfigActivity : ComponentActivity() {
    private var appWidgetId = AppWidgetManager.INVALID_APPWIDGET_ID
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        // Set the result to CANCELED. This will cause the widget host to cancel
        // out of the widget placement if the user presses the back button.
        setResult(RESULT_CANCELED)
        val intent = intent
        val extras = intent.extras
        if (extras != null) {
            appWidgetId = extras.getInt(
                AppWidgetManager.EXTRA_APPWIDGET_ID,
                AppWidgetManager.INVALID_APPWIDGET_ID
            )
        }
 if (appWidgetId == AppWidgetManager.INVALID_APPWIDGET_ID) {
            finish()
            return
        }
        setContent {
            APTrackerTheme {
                MilestonesWidgetConfigScreen(
                    appWidgetId = appWidgetId,
                    onSave = { targetRoomId, roomAlias, customTitle, fontDensity, showFlagEmoji ->
                        saveWidgetPreferences(appWidgetId, targetRoomId, roomAlias, customTitle, fontDensity, showFlagEmoji)
                    },
                    onCancel = {
                        finish()
                    }
                )
            }
        }
    }
    private fun saveWidgetPreferences(
        widgetId: Int,
        targetRoomId: Int,
        roomAlias: String,
        customTitle: String?,
        fontDensity: String,
        showFlagEmoji: Boolean
    ) {
        val prefs = getSharedPreferences("widget_${widgetId}_prefs", Context.MODE_PRIVATE)
        prefs.edit(commit = true) {
            putBoolean("is_configured", true)
            putInt("target_room_id", targetRoomId)
            putString("room_alias", roomAlias)
            putString("custom_title", customTitle?.takeIf { it.isNotBlank() })
            putString("font_density", fontDensity)
            putBoolean("show_flag_emoji", showFlagEmoji)
        }
        val resultValue = Intent().apply {
            putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId)
        }
        setResult(RESULT_OK, resultValue)
        // Bumping the refresh token first is what ensures Glance doesn't display a stale
        // pre-configuration snapshot.
        lifecycleScope.launch {
            try {
                val glanceId = GlanceAppWidgetManager(applicationContext).getGlanceIdBy(widgetId)
                updateAppWidgetState(applicationContext, glanceId) { p ->
                    p[MilestonesWidget.REFRESH_TOKEN] = System.currentTimeMillis()
                }
                MilestonesWidget().update(applicationContext, glanceId)
            } catch (e: Exception) {
                Log.e("MilestonesWidgetConfig", "Failed to update widget $widgetId, falling back to updateAll", e)
                MilestonesWidgetUpdater.update(applicationContext)
            }
            finish()
        }
    }
}
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MilestonesWidgetConfigScreen(
    appWidgetId: Int,
    onSave: (targetRoomId: Int, roomAlias: String, customTitle: String?, fontDensity: String, showFlagEmoji: Boolean) -> Unit,
    onCancel: () -> Unit
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var rooms by remember { mutableStateOf<List<RoomEntity>>(emptyList()) }
    var selectedRoomId by remember { mutableIntStateOf(-1) } // -1 means All Active Rooms
    var customTitle by remember { mutableStateOf("") }
    var selectedDensity by remember { mutableStateOf("standard") }
    var showFlagEmoji by remember { mutableStateOf(true) }
    var searchQuery by remember { mutableStateOf("") }
    var isLoading by remember { mutableStateOf(true) }
    val filteredRooms = remember(rooms, searchQuery) {
        if (searchQuery.isBlank()) rooms else rooms.filter {
            it.alias.contains(searchQuery, ignoreCase = true) ||
            (it.host?.contains(searchQuery, ignoreCase = true) == true)
        }
    }
        LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            val db = AppDatabase.getInstance(context)
            rooms = db.roomDao().getAllRoomsOneShot().filter { !it.is_archived }
            val prefs = context.getSharedPreferences("widget_${appWidgetId}_prefs", Context.MODE_PRIVATE)
            selectedRoomId = prefs.getInt("target_room_id", -1)
            customTitle = prefs.getString("custom_title", "") ?: ""
            selectedDensity = prefs.getString("font_density", "standard") ?: "standard"
            showFlagEmoji = prefs.getBoolean("show_flag_emoji", true)
            isLoading = false
        }
    }
    val selectedRoom = rooms.firstOrNull { it.id == selectedRoomId }
    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        "Milestones Widget Settings",
                        fontWeight = FontWeight.Bold
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onCancel) {
                        Icon(Icons.Default.Close, contentDescription = "Cancel")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface
                )
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp)
        ) {
            if (isLoading) {
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
                           } else {
                LazyColumn(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    item {
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "Choose which room to track, or select All Active Rooms to see all milestones in one widget.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    // Section 1: Room Filter Scope
                    item {
                        Text(
                            text = "Room Scope",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.primary
                        )
                                           }
                    if (rooms.size > 4) {
                        item {
                            OutlinedTextField(
                                value = searchQuery,
                                onValueChange = { searchQuery = it },
                                placeholder = { Text("Search rooms...") },
                                leadingIcon = { Icon(Icons.Default.Search, contentDescription = "Search") },
                                trailingIcon = if (searchQuery.isNotEmpty()) {
                                    {
                                        IconButton(onClick = { searchQuery = "" }) {
                                            Icon(Icons.Default.Clear, contentDescription = "Clear")
                                        }
                                    }
                                } else null,
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                shape = RoundedCornerShape(10.dp)
                            )
                        }
                    }
                                        // Option: All Active Rooms
                    item {
                        Card(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(12.dp))
                                .clickable { selectedRoomId = -1 },
                            colors = CardDefaults.cardColors(
                                containerColor = if (selectedRoomId == -1)
                                    MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.4f)
                                else
                                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f)
                            ),
                            border = if (selectedRoomId == -1)
                                androidx.compose.foundation.BorderStroke(1.5.dp, MaterialTheme.colorScheme.primary)
                            else
                                null
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(14.dp),
                                verticalAlignment = Alignment.CenterVertically
                                                            ) {
                                RadioButton(
                                    selected = selectedRoomId == -1,
                                    onClick = { selectedRoomId = -1 }
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = "All Active Rooms",
                                        fontWeight = FontWeight.SemiBold,
                                        fontSize = 15.sp,
                                        color = MaterialTheme.colorScheme.onSurface
                                    )
                                    Text(
                                        text = "Show combined milestones across all your tracked rooms & slots",
                                        fontSize = 12.5.sp,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                            }
                        }
                    }
                                        // Individual Room Cards
                    if (filteredRooms.isNotEmpty()) {
                        items(filteredRooms, key = { it.id }) { room ->
                            val isSelected = selectedRoomId == room.id
                            Card(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(12.dp))
                                    .clickable { selectedRoomId = room.id },
                                colors = CardDefaults.cardColors(
                                    containerColor = if (isSelected)
                                        MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.4f)
                                    else
                                        MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f)
                                ),
                                border = if (isSelected)
                                    androidx.compose.foundation.BorderStroke(1.5.dp, MaterialTheme.colorScheme.primary)
                                else
                                    null
                            ) {
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(14.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                                                    ) {
                                    RadioButton(
                                        selected = isSelected,
                                        onClick = { selectedRoomId = room.id }
                                    )
                                    Spacer(modifier = Modifier.width(8.dp))
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(
                                            text = room.alias,
                                            fontWeight = FontWeight.SemiBold,
                                            fontSize = 15.sp,
                                            color = MaterialTheme.colorScheme.onSurface
                                        )
                                        val hostText = room.host?.takeIf { it.isNotBlank() } ?: "Archipelago"
                                        val slotCountText = "${room.tracked_slots_count} tracked slot${if (room.tracked_slots_count != 1) "s" else ""}"
                                        Text(
                                            text = "$hostText • $slotCountText",
                                            fontSize = 12.5.sp,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant
                                        )
                                    }
                                }
                            }
                        }
                    }
                    // Section 2: Display & Density
                    item {
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = "Display Options",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }
                                       item {
                        val placeholderTitle = if (selectedRoomId == -1) "All Rooms" else (selectedRoom?.alias ?: "Milestones")
                        OutlinedTextField(
                            value = customTitle,
                            onValueChange = { customTitle = it },
                            label = { Text("Custom Widget Title (Optional)") },
                            placeholder = { Text(placeholderTitle) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            shape = RoundedCornerShape(10.dp)
                        )
                    }
                    item {
                        Text(
                            text = "Layout Density",
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onSurface
                        )
                    }
                    item {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            DensityOptionCard(
                                title = "Standard",
                                description = "Larger text & spacing",
                                isSelected = selectedDensity == "standard",
                                onClick = { selectedDensity = "standard" },
                                modifier = Modifier.weight(1f)
                            )
                                                        DensityOptionCard(
                                title = "Compact",
                                description = "More milestones visible",
                                isSelected = selectedDensity == "compact",
                                onClick = { selectedDensity = "compact" },
                                modifier = Modifier.weight(1f)
                            )
                        }
                    }
                    item {
                        ToggleOptionRow(
                            title = "Show flag emoji",
                            description = "Prefix each milestone with a flag. Turn off for a plainer list.",
                            checked = showFlagEmoji,
                            onCheckedChange = { showFlagEmoji = it }
                        )
                    }
                    item {
                        Spacer(modifier = Modifier.height(16.dp))
                    }
                }
                Button(
                    onClick = {
                        val roomAlias = if (selectedRoomId == -1) "All Rooms" else (selectedRoom?.alias ?: "Milestones")
                        onSave(selectedRoomId, roomAlias, customTitle, selectedDensity, showFlagEmoji)
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 12.dp)
                        .height(50.dp),
                    shape = RoundedCornerShape(12.dp)
                ) {
                                        Text(
                        text = "Save Widget",
                        fontWeight = FontWeight.Bold,
                        fontSize = 16.sp
                    )
                }
            }
        }
    }
}
@Composable
private fun DensityOptionCard(
    title: String,
    description: String,
    isSelected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier
            .clip(RoundedCornerShape(12.dp))
            .clickable(onClick = onClick),
        colors = CardDefaults.cardColors(
            containerColor = if (isSelected)
                MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.4f)
            else
            MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f)
        ),
        border = if (isSelected)
            androidx.compose.foundation.BorderStroke(1.5.dp, MaterialTheme.colorScheme.primary)
        else
            null
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Bold,
                    color = if (isSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface
                )
                if (isSelected) {
                                    Icon(
                        imageVector = Icons.Default.Check,
                        contentDescription = "Selected",
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(16.dp)
                    )
                }
            }
            Spacer(modifier = Modifier.height(2.dp))
            Text(
                text = description,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}