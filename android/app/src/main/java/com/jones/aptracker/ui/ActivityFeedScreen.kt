package com.jones.aptracker.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ActivityFeedScreen(
    historyViewModel: HistoryViewModel = viewModel(),
    // 1. Accept the UserViewModel (defaults to a new instance if not passed)
    userViewModel: UserViewModel = viewModel()
) {
    Scaffold(

    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = padding.calculateTopPadding())
        ) {
            HistoryContent(
                roomId = null,
                historyViewModel = historyViewModel,
                userViewModel = userViewModel
            )
        }
    }
}