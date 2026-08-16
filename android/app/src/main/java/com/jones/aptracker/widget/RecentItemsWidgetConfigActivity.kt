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
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.ViewDay
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
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
import androidx.compose.runtime.rememberCoroutineScope
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

class RecentItemsWidgetConfigActivity : ComponentActivity() {

    private var appWidgetId = AppWidgetManager.INVALID_APPWIDGET_ID

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)

        // Set the result to CANCELED. This will cause the widget host to cancel
        // out of the widget placement if the user presses the back button.
        setResult(RESULT_CANCELED)

        // Find the widget id from the intent.
        val intent = intent
        val extras = intent.extras
        if (extras != null) {
            appWidgetId = extras.getInt(
                AppWidgetManager.EXTRA_APPWIDGET_ID,
                AppWidgetManager.INVALID_APPWIDGET_ID
            )
        }

        // If this activity was started with an invalid widget ID, finish.
        if (appWidgetId == AppWidgetManager.INVALID_APPWIDGET_ID) {
            finish()
            return
        }

        setContent {
            APTrackerTheme {
                WidgetConfigScreen(
                    appWidgetId = appWidgetId,
                    onSave = { targetRoomId, fontDensity, customTitle, showItemDots ->
                        saveWidgetPreferences(appWidgetId, targetRoomId, fontDensity, customTitle, showItemDots)
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
        fontDensity: String,
        customTitle: String?,
        showItemDots: Boolean
    ) {
        val prefs = getSharedPreferences("widget_${widgetId}_prefs", Context.MODE_PRIVATE)
        prefs.edit(commit = true) {
            putBoolean("is_configured", true)
            putInt("target_room_id", targetRoomId)
            putString("font_density", fontDensity)
            putString("custom_title", customTitle?.takeIf { it.isNotBlank() })
            putBoolean("show_item_dots", showItemDots)
        }

        // Set result eagerly so the launcher always receives RESULT_OK upon activity completion
        val resultValue = Intent().apply {
            putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId)
        }
        setResult(RESULT_OK, resultValue)

        // Widgets with a configuration activity receive NO automatic update broadcast, even after
        // RESULT_OK, so the first composition is our responsibility here. The token bump matters as
        // much as the update() call: if the launcher already started a Glance session for this
        // widget before configuration finished, update() would only recompose that session's cached
        // state and the widget would keep showing its pre-config view.
        lifecycleScope.launch {
            try {
                val glanceId = GlanceAppWidgetManager(applicationContext).getGlanceIdBy(widgetId)
                updateAppWidgetState(applicationContext, glanceId) { prefs ->
                    prefs[RecentItemsWidget.REFRESH_TOKEN] = System.currentTimeMillis()
                }
                RecentItemsWidget().update(applicationContext, glanceId)
            } catch (e: Exception) {
                Log.e("WidgetConfig", "Failed to update widget $widgetId, falling back to updateAll", e)
                RecentItemsWidgetUpdater.update(applicationContext)
            }
            finish()
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun WidgetConfigScreen(
    appWidgetId: Int,
    onSave: (targetRoomId: Int, fontDensity: String, customTitle: String?, showItemDots: Boolean) -> Unit,
    onCancel: () -> Unit
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var rooms by remember { mutableStateOf<List<RoomEntity>>(emptyList()) }
    var selectedRoomId by remember { mutableIntStateOf(-1) } // -1 means all active rooms
    var selectedDensity by remember { mutableStateOf("standard") } // "standard" or "compact"
    var customTitle by remember { mutableStateOf("") }
    var showItemDots by remember { mutableStateOf(true) }
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
            selectedDensity = prefs.getString("font_density", "standard") ?: "standard"
            customTitle = prefs.getString("custom_title", "") ?: ""
            showItemDots = prefs.getBoolean("show_item_dots", true)
            isLoading = false
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        "Widget Settings",
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
            LazyColumn(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "Customize how recent items are displayed on your home screen.",
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
                                    text = "Show combined recent activity across all your tracked slots",
                                    fontSize = 12.5.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                        }
                    }
                }

                if (filteredRooms.isNotEmpty()) {
                    items(filteredRooms, key = { it.id }) { room ->
                        Card(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(12.dp))
                                .clickable { selectedRoomId = room.id },
                            colors = CardDefaults.cardColors(
                                containerColor = if (selectedRoomId == room.id)
                                    MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.4f)
                                else
                                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f)
                            ),
                            border = if (selectedRoomId == room.id)
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
                                    selected = selectedRoomId == room.id,
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
                                    val hostInfo = room.host?.takeIf { it.isNotBlank() } ?: "Archipelago Room"
                                    Text(
                                        text = "$hostInfo • ${room.tracked_slots_count} tracked slots",
                                        fontSize = 12.5.sp,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                            }
                        }
                    }
                }

                // Section 2: Display Density
                item {
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "Display Density",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.primary
                    )
                }

                item {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        // Standard Density Card
                        Card(
                            modifier = Modifier
                                .weight(1f)
                                .clip(RoundedCornerShape(12.dp))
                                .clickable { selectedDensity = "standard" },
                            colors = CardDefaults.cardColors(
                                containerColor = if (selectedDensity == "standard")
                                    MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.4f)
                                else
                                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f)
                            ),
                            border = if (selectedDensity == "standard")
                                androidx.compose.foundation.BorderStroke(1.5.dp, MaterialTheme.colorScheme.primary)
                            else
                                null
                        ) {
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(14.dp),
                                horizontalAlignment = Alignment.CenterHorizontally
                            ) {
                                RadioButton(
                                    selected = selectedDensity == "standard",
                                    onClick = { selectedDensity = "standard" }
                                )
                                Text(
                                    text = "Standard",
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 14.5.sp,
                                    color = MaterialTheme.colorScheme.onSurface
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = "Larger, comfortable typography",
                                    fontSize = 11.5.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    lineHeight = 14.sp
                                )
                            }
                        }

                        // Compact Density Card
                        Card(
                            modifier = Modifier
                                .weight(1f)
                                .clip(RoundedCornerShape(12.dp))
                                .clickable { selectedDensity = "compact" },
                            colors = CardDefaults.cardColors(
                                containerColor = if (selectedDensity == "compact")
                                    MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.4f)
                                else
                                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f)
                            ),
                            border = if (selectedDensity == "compact")
                                androidx.compose.foundation.BorderStroke(1.5.dp, MaterialTheme.colorScheme.primary)
                            else
                                null
                        ) {
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(14.dp),
                                horizontalAlignment = Alignment.CenterHorizontally
                            ) {
                                RadioButton(
                                    selected = selectedDensity == "compact",
                                    onClick = { selectedDensity = "compact" }
                                )
                                Text(
                                    text = "Compact",
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 14.5.sp,
                                    color = MaterialTheme.colorScheme.onSurface
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = "Tighter rows to fit more items",
                                    fontSize = 11.5.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    lineHeight = 14.sp
                                )
                            }
                        }
                    }
                }

                // Section 3: Appearance
                item {
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "Appearance",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.primary
                    )
                }

                item {
                    val selectedRoom = rooms.firstOrNull { it.id == selectedRoomId }
                    val placeholderTitle = if (selectedRoomId == -1) {
                        "Archipelago Alerts"
                    } else {
                        selectedRoom?.alias ?: "Archipelago Alerts"
                    }
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
                    ToggleOptionRow(
                        title = "Show item color dots",
                        description = "Color-coded dot before each item marking its category.",
                        checked = showItemDots,
                        onCheckedChange = { showItemDots = it }
                    )
                }

                item {
                    Spacer(modifier = Modifier.height(16.dp))
                }
            }

            Button(
                onClick = { onSave(selectedRoomId, selectedDensity, customTitle, showItemDots) },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 12.dp),
                shape = RoundedCornerShape(10.dp)
            ) {
                Text(
                    text = "Apply Settings",
                    fontWeight = FontWeight.Bold,
                    fontSize = 15.sp,
                    modifier = Modifier.padding(vertical = 4.dp)
                )
            }
        }
    }
}
