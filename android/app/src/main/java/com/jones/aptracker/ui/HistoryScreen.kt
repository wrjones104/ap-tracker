package com.jones.aptracker.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jones.aptracker.network.HistoryItem
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryScreen(roomId: Int, roomAlias: String, historyViewModel: HistoryViewModel = viewModel()) {
    var selectedTabIndex by remember { mutableStateOf(0) }
    val tabs = listOf("Received Items", "Hints")

    // Get the state from the ViewModel
    val isLoading by historyViewModel.isLoading
    val errorMessage = historyViewModel.errorMessage.value

    LaunchedEffect(key1 = roomId) {
        historyViewModel.fetchHistory(roomId)
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text("$roomAlias - History") }) }
    ) { innerPadding ->
        Column(modifier = Modifier.padding(innerPadding)) {
            TabRow(selectedTabIndex = selectedTabIndex) {
                tabs.forEachIndexed { index, title ->
                    Tab(
                        selected = selectedTabIndex == index,
                        onClick = { selectedTabIndex = index },
                        text = { Text(title) }
                    )
                }
            }

            // Box to manage the content state (loading, error, empty, or list)
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center // Center the loading/error/empty states
            ) {
                if (isLoading) {
                    CircularProgressIndicator()
                } else if (errorMessage != null) {
                    Text(
                        text = errorMessage,
                        modifier = Modifier.padding(16.dp),
                        color = Color.Red
                    )
                } else {
                    val itemsToShow = when (selectedTabIndex) {
                        0 -> historyViewModel.itemHistory.value
                        1 -> historyViewModel.hintHistory.value
                        else -> emptyList() // <-- THE FIX: Add this exhaustive else case
                    }

                    if (itemsToShow.isEmpty()) {
                        Text("No history found for your tracked slots.")
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

    LazyColumn(contentPadding = PaddingValues(16.dp)) {
        items(items) { item ->
            Column(modifier = Modifier.padding(vertical = 8.dp)) {
                Text(text = item.message)
                Text(
                    text = formatTimestamp(item.timestamp, formatter),
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.Gray
                )
            }
            Divider()
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