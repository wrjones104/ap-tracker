package com.jones.aptracker.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ActivityFeedScreen(
    historyViewModel: HistoryViewModel = viewModel(),
    userViewModel: UserViewModel = viewModel(),
    onNavigateToSlotDetail: ((Int, Int) -> Unit)? = null,
    onBackClick: (() -> Unit)? = null
) {
    Scaffold(
        contentWindowInsets = WindowInsets(0.dp),
        topBar = {
            // Only shown when this screen is pushed as its own destination (e.g. from
            // SlotDetailScreen). Embedded in the Activity bottom-nav tab, MainScreen owns the bar.
            if (onBackClick != null) {
                val historyFilter by historyViewModel.historyFilter.collectAsState()
                val roomNames by historyViewModel.roomNames.collectAsState()
                val titleText = when (val filter = historyFilter) {
                    HistoryFilter.Active -> "Active Rooms"
                    HistoryFilter.Archived -> "Archived Rooms"
                    HistoryFilter.All -> "All History"
                    is HistoryFilter.Specific -> roomNames[filter.roomId] ?: "Room History"
                }
                TopAppBar(
                    title = { Text(titleText) },
                    navigationIcon = {
                        IconButton(onClick = onBackClick) {
                            Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                        }
                    }
                )
            }
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            HistoryContent(
                historyViewModel = historyViewModel,
                userViewModel = userViewModel,
                onNavigateToSlotDetail = onNavigateToSlotDetail
            )
        }
    }
}