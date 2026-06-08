package com.jones.aptracker.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.time.temporal.ChronoUnit

@Composable
fun SnoozeDialog(
    title: String = "Snooze Notifications",
    currentSnoozeUntil: String? = null,
    activeSnoozeDetails: List<String> = emptyList(),
    dateFormatPreset: DateFormatPreset = DateFormatPreset.SYSTEM_DEFAULT,
    onDismiss: () -> Unit,
    onSnoozeSelected: (Int) -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                // 1. Show Global Snooze Status
                if (currentSnoozeUntil != null) {
                    Text("Global Snooze active until: ${formatIsoDate(currentSnoozeUntil, dateFormatPreset)}")
                    Spacer(Modifier.height(16.dp))
                }

                // 2. Show Specific Slot Snoozes (NEW)
                if (activeSnoozeDetails.isNotEmpty()) {
                    Text("Currently Snoozed:", style = MaterialTheme.typography.labelMedium)
                    activeSnoozeDetails.forEach { detail ->
                        Text("• $detail", style = MaterialTheme.typography.bodySmall)
                    }
                    Spacer(Modifier.height(16.dp))
                }

                // 3. "Wake Up" Button (Clear All)
                // Show this if ANYTHING is snoozed (Global OR Slots)
                if (currentSnoozeUntil != null || activeSnoozeDetails.isNotEmpty()) {
                    Button(
                        onClick = { onSnoozeSelected(0) }, // 0 = Clear All
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
                    ) {
                        Text("Wake Up (Clear All Snoozes)")
                    }

                    // Divider to separate "Wake Up" from "Overwrite" options
                    Spacer(Modifier.height(16.dp))
                    HorizontalDivider()
                    Spacer(Modifier.height(16.dp))
                    Text("Or overwrite with Global Snooze:", style = MaterialTheme.typography.labelSmall)
                }

                // 4. Standard Snooze Options
                SnoozeOptionButton("1 Hour", 60, onSnoozeSelected)
                SnoozeOptionButton("4 Hours", 240, onSnoozeSelected)
                SnoozeOptionButton("8 Hours", 480, onSnoozeSelected)
                SnoozeOptionButton("24 Hours", 1440, onSnoozeSelected)
            }
        },
        confirmButton = {},
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        }
    )
}

@Composable
fun SnoozeOptionButton(text: String, minutes: Int, onSelect: (Int) -> Unit) {
    OutlinedButton(
        onClick = { onSelect(minutes) },
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)
    ) {
        Text(text)
    }
}

fun formatIsoDate(isoString: String, dateFormatPreset: DateFormatPreset = DateFormatPreset.SYSTEM_DEFAULT): String {
    return try {
        // 1. Parse the incoming string.
        val cleanedString = isoString.replace("Z", "")

        // 2. Treat the parsed time as UTC
        val utcTime = LocalDateTime.parse(cleanedString)
            .atZone(ZoneId.of("UTC"))

        // 3. Convert to the System Default (User's local timezone)
        val localTime = utcTime.withZoneSameInstant(ZoneId.systemDefault())

        // 4. Format nicely
        val formatter = dateFormatPreset.getFormatter(isDetail = true)

        localTime.format(formatter)
    } catch (e: Exception) {
        // Fallback: If parsing fails, just show a cleaned up version of the raw string
        isoString.replace("T", " ").substringBeforeLast(".")
    }
}