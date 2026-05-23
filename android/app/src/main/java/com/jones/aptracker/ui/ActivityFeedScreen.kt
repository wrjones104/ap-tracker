package com.jones.aptracker.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ActivityFeedScreen(
    historyViewModel: HistoryViewModel = viewModel(),
    userViewModel: UserViewModel = viewModel(),
    onNavigateToSlotDetail: ((Int, Int) -> Unit)? = null
) {
    Scaffold(
        contentWindowInsets = WindowInsets(0.dp)
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