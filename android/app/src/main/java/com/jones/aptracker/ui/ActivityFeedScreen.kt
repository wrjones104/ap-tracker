package com.jones.aptracker.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ActivityFeedScreen(
    // We instantiate the viewModel here so it survives tab switches
    // within the MainScreen scope if using proper scoping,
    // or just let it recreate (it's lightweight).
    historyViewModel: HistoryViewModel = viewModel()
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Activity Feed") }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            // Reusing the refactored content!
            // roomId = null signals "Global History"
            HistoryContent(
                roomId = null,
                historyViewModel = historyViewModel
            )
        }
    }
}