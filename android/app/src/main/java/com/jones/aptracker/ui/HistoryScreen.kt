package com.jones.aptracker.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jones.aptracker.network.HistoryItem
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import androidx.compose.material3.TextFieldDefaults

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryScreen(
    roomId: Int?,
    roomAlias: String?,
    historyViewModel: HistoryViewModel = viewModel()
) {
    val isLoading by historyViewModel.isLoading.collectAsState()
    val errorMessage by historyViewModel.errorMessage
    val fullHistory by historyViewModel.itemHistory.collectAsState()
    val searchQuery by historyViewModel.searchQuery

    val itemsToShow = remember(fullHistory, searchQuery) {
        if (searchQuery.isBlank()) {
            fullHistory
        } else {
            fullHistory.filter {
                it.message.contains(searchQuery, ignoreCase = true)
            }
        }
    }

    LaunchedEffect(key1 = roomId) {
        historyViewModel.loadHistoryFor(roomId)
    }

    Scaffold(
        topBar = {
            val title = if (roomAlias != null) "$roomAlias - Item History" else "All Item History"
            TopAppBar(title = { Text(title) })
        }
    ) { innerPadding ->
        Column(modifier = Modifier.padding(innerPadding)) {
            TextField(
                value = searchQuery,
                onValueChange = { historyViewModel.onSearchQueryChanged(it) },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                label = { Text("Search History") },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = "Search") },
                singleLine = true,
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = Color.Transparent,
                    unfocusedContainerColor = Color.Transparent,
                    disabledContainerColor = Color.Transparent
                )
            )

            Box(
                modifier = Modifier.fillMaxSize(),
                // --- THE FIX IS HERE: Changed from Center to TopCenter ---
                contentAlignment = Alignment.TopCenter
            ) {
                if (isLoading && fullHistory.isEmpty()) {
                    CircularProgressIndicator()
                } else if (errorMessage != null) {
                    Text(
                        text = errorMessage!!,
                        modifier = Modifier.padding(16.dp),
                        color = Color.Red
                    )
                } else {
                    if (itemsToShow.isEmpty()) {
                        val emptyText = if (searchQuery.isNotBlank()) {
                            "No results found."
                        } else {
                            "No history found for your tracked slots."
                        }
                        Text(emptyText, modifier = Modifier.padding(top = 24.dp)) // Add some padding
                    } else {
                        HistoryList(items = itemsToShow)
                    }
                }
            }
        }
    }
}

@Composable
fun HistoryList(items: List<HistoryItem>) {
    val formatter = remember { DateTimeFormatter.ofPattern("MMM d, h:mm a") }
    val context = LocalContext.current

    LazyColumn(contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp)) {
        items(items) { item ->
            val isClickable = item.tracker_id != null && item.slot_id != null

            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 6.dp)
                    .clickable(enabled = isClickable) {
                        val url = "https://archipelago.gg/tracker/${item.tracker_id}/0/${item.slot_id}"
                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                        context.startActivity(intent)
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

                    Column {
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

private fun formatTimestamp(isoString: String, formatter: DateTimeFormatter): String {
    return try {
        val instant = Instant.parse(isoString)
        val localDateTime = LocalDateTime.ofInstant(instant, ZoneId.systemDefault())
        localDateTime.format(formatter)
    } catch (e: Exception) {
        e.printStackTrace()
        "Invalid date"
    }
}