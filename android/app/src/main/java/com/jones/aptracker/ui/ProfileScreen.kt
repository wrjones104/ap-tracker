package com.jones.aptracker.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(
    userViewModel: UserViewModel = viewModel(),
    onBackClick: () -> Unit
) {
    val userProfile by userViewModel.userProfile.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Settings") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp)
        ) {
            Text(
                text = "Global Notification Defaults",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(bottom = 16.dp)
            )

            // We use userProfile?.let to wait until the profile has loaded
            userProfile?.let { profile ->
                NotificationToggle(
                    text = "Progression Items",
                    checked = profile.notify_progression_default,
                    onCheckedChange = {
                        userViewModel.updateGlobalPreferences(progression = it)
                    }
                )
                NotificationToggle(
                    text = "Useful Items",
                    checked = profile.notify_useful_default,
                    onCheckedChange = {
                        userViewModel.updateGlobalPreferences(useful = it)
                    }
                )
                NotificationToggle(
                    text = "Hints",
                    checked = profile.notify_hints_default,
                    onCheckedChange = {
                        userViewModel.updateGlobalPreferences(hints = it)
                    }
                )
            } ?: run {
                // Show a loading indicator while the profile loads
                Box(
                    modifier = Modifier.fillMaxWidth(),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator()
                }
            }
        }
    }
}

@Composable
private fun NotificationToggle(
    text: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(text, style = MaterialTheme.typography.bodyLarge)
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange
        )
    }
}