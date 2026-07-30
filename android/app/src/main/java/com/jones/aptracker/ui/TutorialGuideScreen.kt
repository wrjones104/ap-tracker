package com.jones.aptracker.ui

import androidx.annotation.DrawableRes
import com.jones.aptracker.R
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.HelpOutline
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

data class FaqTopic(
    val id: String,
    val title: String,
    val summary: String,
    val detailedSteps: List<String>,
    val screenshotCaption: String? = null,
    @param:DrawableRes val imageRes: Int? = null
)


@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TutorialGuideScreen(
    onBackClick: () -> Unit
) {
    val topics = remember {
        listOf(
            FaqTopic(
                id = "add_room",
                title = "How do I track an Archipelago room?",
                summary = "Connect to your Archipelago multiworld game using its room URL.",
                detailedSteps = listOf(
                    "Navigate to the Rooms tab and tap the (+) Floating Action Button.",
                    "Paste your Archipelago room URL (e.g. https://archipelago.gg/room/12345).",
                    "Assign a room nickname if desired and save.",
                    "Pick player slots and customize push notifications."
                ),
                screenshotCaption = "Rooms Tab: Tap (+) to add a multiworld room",
                imageRes = R.drawable.faq_room
            ),
            FaqTopic(
                id = "mutes_whitelist",
                title = "What is the difference between Ignores and Whitelists?",
                summary = "Ignore spammy items, or guarantee notifications for specific items.",
                detailedSteps = listOf(
                    "Ignore List (Mutes): Suppresses push notifications and activity feed logs for spammy items.",
                    "Whitelist: Priority overrides that ALWAYS send a push notification when received.",
                    "Global vs Per-Game: Both mutes and whitelists can apply to all games or be scoped to a specific game."
                ),
                screenshotCaption = "Whitelist Screen: Mark priority items to bypass mutes",
                imageRes = R.drawable.faq_ignore
            ),
            FaqTopic(
                id = "threshold_groups",
                title = "How do Milestone Threshold Groups work?",
                summary = "Combine multiple required items into custom groups with AND logic.",
                detailedSteps = listOf(
                    "Open a player slot's detail screen and tap 'Threshold Groups'.",
                    "Create a named group (e.g. 'Sword & Shield').",
                    "Add required item names or item groups.",
                    "You will receive a single milestone notification once ALL items in the group are collected."
                ),
                screenshotCaption = "Threshold Group Builder: Combine items with AND logic",
                imageRes = R.drawable.faq_milestone
            ),
            FaqTopic(
                id = "cheese_tracker",
                title = "How do I sync with Cheese Tracker?",
                summary = "Automatically import tracked rooms and slot claims from Cheese Tracker.",
                detailedSteps = listOf(
                    "Go to Settings -> Connected Accounts.",
                    "Enter your Cheese Tracker API key.",
                    "Your tracked rooms and slot claims will automatically stay synced bidirectionally."
                ),
                screenshotCaption = "Connected Accounts: Auto-sync slots with Cheese Tracker",
                imageRes = R.drawable.faq_cheese
            ),
            FaqTopic(
                id = "notifications",
                title = "Why am I not receiving push notifications?",
                summary = "Troubleshoot Android background battery optimizations and FCM delivery.",
                detailedSteps = listOf(
                    "Ensure notification permissions are granted in Android System Settings.",
                    "Disable battery optimization for Archipelago Alerts so background pushes deliver instantly.",
                    "Tap 'Send Test Notification' in Settings to verify FCM push setup."
                ),
                screenshotCaption = "Settings Screen: Verify test notification delivery",
                imageRes = R.drawable.faq_debug
            )
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Guide & FAQ") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            // Intro Card
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.5f)
                )
            ) {
                Row(
                    modifier = Modifier.padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.HelpOutline,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary
                    )
                    Text(
                        text = "Learn how to get the most out of Archipelago Alerts.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onPrimaryContainer
                    )
                }
            }

            Spacer(modifier = Modifier.height(4.dp))

            // Accordion Topic Items
            topics.forEach { topic ->
                FaqAccordionCard(topic = topic)
            }
        }
    }
}

@Composable
private fun FaqAccordionCard(topic: FaqTopic) {
    var expanded by remember { mutableStateOf(false) }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { expanded = !expanded },
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f)
        )
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = topic.title,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    if (!expanded) {
                        Text(
                            text = topic.summary,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.8f),
                            modifier = Modifier.padding(top = 4.dp)
                        )
                    }
                }
                Icon(
                    imageVector = if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary
                )
            }

            AnimatedVisibility(
                visible = expanded,
                enter = fadeIn() + expandVertically(),
                exit = fadeOut() + shrinkVertically()
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    Spacer(modifier = Modifier.height(4.dp))

                    topic.detailedSteps.forEach { step ->
                        Row(
                            verticalAlignment = Alignment.Top,
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Text(
                                text = "•",
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = FontWeight.Bold,
                                color = MaterialTheme.colorScheme.primary
                            )
                            Text(
                                text = step,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }

                    // Optional Screenshot Preview Container
                    if (topic.screenshotCaption != null) {
                        Spacer(modifier = Modifier.height(8.dp))
                        ScreenshotPreviewCard(
                            caption = topic.screenshotCaption,
                            imageRes = topic.imageRes
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ScreenshotPreviewCard(
    caption: String,
    @DrawableRes imageRes: Int? = null
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .border(
                1.dp,
                MaterialTheme.colorScheme.outline.copy(alpha = 0.3f),
                RoundedCornerShape(12.dp)
            ),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface
        )
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            if (imageRes != null) {
                Image(
                    painter = painterResource(id = imageRes),
                    contentDescription = caption,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(8.dp)),
                    contentScale = ContentScale.FillWidth
                )
            } else {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(100.dp)
                        .background(
                            MaterialTheme.colorScheme.surfaceVariant,
                            shape = RoundedCornerShape(8.dp)
                        ),
                    contentAlignment = Alignment.Center
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        Icon(
                            imageVector = Icons.Default.Info,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.onSurfaceVariant
                        )

                        Text(
                            text = "App Interface Preview",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(6.dp))

            Surface(
                shape = RoundedCornerShape(16.dp),
                color = MaterialTheme.colorScheme.secondaryContainer
            ) {
                Text(
                    text = caption,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSecondaryContainer,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp)
                )
            }
        }
    }
}
