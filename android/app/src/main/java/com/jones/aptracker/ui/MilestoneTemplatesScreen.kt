package com.jones.aptracker.ui

import android.content.Intent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Upload
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jones.aptracker.network.MilestoneTemplate
import com.jones.aptracker.network.ParsedTemplate
import com.jones.aptracker.network.TemplateImportResult
import com.jones.aptracker.network.ThresholdGroupItemRequest
import com.jones.aptracker.network.exportMilestoneTemplates
import com.jones.aptracker.network.parseMilestoneTemplateShareString

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MilestoneTemplatesScreen(
    userViewModel: UserViewModel = viewModel(),
    onBackClick: () -> Unit
) {
    val milestoneTemplates by userViewModel.milestoneTemplates.collectAsState()
    val gameAvailableItems by userViewModel.gameAvailableItems.collectAsState()
    val integrationMessage by userViewModel.integrationMessage.collectAsState()
    val errorMessage by userViewModel.errorMessage.collectAsState()

    val context = LocalContext.current

    var editingTemplate by remember { mutableStateOf<MilestoneTemplate?>(null) }
    var deletingTemplate by remember { mutableStateOf<MilestoneTemplate?>(null) }
    var showImportDialog by remember { mutableStateOf(false) }

    // --- Create-from-here state ---
    // A template is per-game, so creating one from this screen needs a game chosen
    // first; on the slot detail screen the slot supplies it.
    var showGamePicker by remember { mutableStateOf(false) }
    var creatingForGame by remember { mutableStateOf<String?>(null) }
    var createConflict by remember { mutableStateOf<TemplateConflict?>(null) }

    val trackedSlotsByRoom by userViewModel.trackedSlotsByRoom.collectAsState()
    val knownGames by userViewModel.knownGames.collectAsState()
    val isKnownGamesLoading by userViewModel.isKnownGamesLoading.collectAsState()
    val isGameItemsLoading by userViewModel.isGameItemsLoading.collectAsState()

    // The games the user has a reason to care about: anything they track, plus anything
    // they already have a template for, so a game dropped from tracking can still take
    // a second template. These get pinned to the top of the picker.
    val myGames = remember(trackedSlotsByRoom, milestoneTemplates) {
        (trackedSlotsByRoom.flatMap { room -> room.tracked_slots.mapNotNull { it.game } } +
            milestoneTemplates.map { it.game_name })
            .filter { it.isNotBlank() }
            .distinctBy { it.lowercase() }
            .sortedBy { it.lowercase() }
    }

    // Everything else the server has a datapackage for. A template only needs the item
    // list, not a slot, so there is no reason to require having played the game first.
    val otherGames = remember(knownGames, myGames) {
        val mine = myGames.map { it.lowercase() }.toSet()
        knownGames
            .filter { it.isNotBlank() && it.lowercase() !in mine }
            .distinctBy { it.lowercase() }
            .sortedBy { it.lowercase() }
    }

    // --- Sequential import queue state ---
    var importItems by remember { mutableStateOf<List<ParsedTemplate>>(emptyList()) }
    var importIndex by remember { mutableStateOf(0) }
    var importConflict by remember { mutableStateOf<ParsedTemplate?>(null) }
    val importLog = remember { mutableStateListOf<String>() }

    LaunchedEffect(Unit) {
        userViewModel.fetchMilestoneTemplates()
        // Populates the game picker. This screen is reachable without visiting Rooms
        // first, so the list cannot be assumed to be loaded already.
        userViewModel.fetchTrackedSlots()
        // The rest of the picker: every game the server knows a datapackage for.
        userViewModel.fetchKnownGames()
    }

    LaunchedEffect(integrationMessage) {
        integrationMessage?.let {
            android.widget.Toast.makeText(context, it, android.widget.Toast.LENGTH_SHORT).show()
            userViewModel.clearIntegrationMessage()
        }
    }

    LaunchedEffect(errorMessage) {
        errorMessage?.let {
            android.widget.Toast.makeText(context, it, android.widget.Toast.LENGTH_LONG).show()
            userViewModel.clearErrorMessage()
        }
    }

    // Drives the import queue: process one parsed template at a time, pausing
    // whenever a 409 needs the user to pick overwrite/skip.
    LaunchedEffect(importItems, importIndex, importConflict) {
        if (importConflict != null) return@LaunchedEffect
        if (importIndex !in importItems.indices) return@LaunchedEffect
        val current = importItems[importIndex]
        userViewModel.createMilestoneTemplate(
            name = current.name,
            gameName = current.game,
            items = current.items.map { ThresholdGroupItemRequest(it.itemName, it.quantity, it.isGroup) },
            onConflict = { importConflict = current },
            onSuccess = {
                importLog.add("Created \"${current.name}\" for ${current.game}.")
                importIndex += 1
            },
            onError = {
                importLog.add("Failed \"${current.name}\" for ${current.game}.")
                importIndex += 1
            },
            notify = false
        )
    }

    val grouped = remember(milestoneTemplates) {
        milestoneTemplates
            .sortedBy { it.name.lowercase() }
            .groupBy { it.game_name }
            .toSortedMap(compareBy { it.lowercase() })
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Milestone Templates") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(onClick = { showGamePicker = true }) {
                        Icon(Icons.Default.Add, contentDescription = "New Template")
                    }
                    IconButton(onClick = { showImportDialog = true }) {
                        Icon(Icons.Default.Upload, contentDescription = "Import Templates")
                    }
                }
            )
        }
    ) { padding ->
        if (milestoneTemplates.isEmpty()) {
            Column(
                modifier = Modifier
                    .padding(padding)
                    .fillMaxSize()
            ) {
                Box(modifier = Modifier.padding(16.dp)) {
                    TemplatesTips()
                }
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth(),
                    contentAlignment = Alignment.Center
                ) {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier.padding(horizontal = 32.dp)
                    ) {
                        Text(
                            "No templates saved yet.",
                            style = MaterialTheme.typography.titleMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            textAlign = TextAlign.Center
                        )
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "Build one here, save a milestone group as a template from a slot's detail screen, or import one below.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = Color.Gray,
                            textAlign = TextAlign.Center
                        )
                        Spacer(Modifier.height(16.dp))
                        Button(onClick = { showGamePicker = true }) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(4.dp))
                                Text("New Template")
                            }
                        }
                        TextButton(onClick = { showImportDialog = true }) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Default.Upload, contentDescription = null, modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(4.dp))
                                Text("Import a Template")
                            }
                        }
                    }
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .padding(padding)
                    .fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                item(key = "tips") {
                    TemplatesTips()
                }
                grouped.forEach { (gameName, templates) ->
                    item(key = "header_$gameName") {
                        Text(
                            gameName,
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.padding(top = 8.dp, bottom = 4.dp)
                        )
                    }
                    items(templates, key = { it.id }) { template ->
                        MilestoneTemplateCard(
                            template = template,
                            onEdit = { editingTemplate = template },
                            onDelete = { deletingTemplate = template },
                            onExport = {
                                val shareString = exportMilestoneTemplates(listOf(template))
                                val sendIntent = Intent(Intent.ACTION_SEND).apply {
                                    type = "text/plain"
                                    putExtra(Intent.EXTRA_TEXT, shareString)
                                    putExtra(Intent.EXTRA_SUBJECT, "Milestone Template: ${template.name}")
                                }
                                context.startActivity(Intent.createChooser(sendIntent, "Share Template"))
                            }
                        )
                    }
                }
            }
        }
    }

    if (showGamePicker) {
        GamePickerDialog(
            myGames = myGames,
            otherGames = otherGames,
            isLoadingOtherGames = isKnownGamesLoading,
            onDismiss = { showGamePicker = false },
            onSelect = { game ->
                showGamePicker = false
                creatingForGame = game
            }
        )
    }

    val newGame = creatingForGame
    if (newGame != null) {
        LaunchedEffect(newGame) {
            userViewModel.fetchGameAvailableItems(newGame)
        }
        ThresholdGroupSheet(
            // Name the game: the picker is a separate step, so by the time the editor is
            // open there is otherwise nothing on screen saying which game was chosen.
            title = "New Template · $newGame",
            confirmLabel = "Create",
            initialItems = emptyList(),
            availableItems = gameAvailableItems,
            isAutocompleteLoading = isGameItemsLoading,
            nameRequired = true,
            onDismiss = {
                creatingForGame = null
                userViewModel.clearGameAvailableItems()
            },
            onConfirm = { name, items, _ ->
                // nameRequired gates the confirm button on a non-blank name, so this is
                // only defensive.
                val templateName = name?.trim()
                if (!templateName.isNullOrBlank()) {
                    userViewModel.createMilestoneTemplate(
                        name = templateName,
                        gameName = newGame,
                        items = items,
                        onConflict = {
                            createConflict = TemplateConflict(items, templateName, newGame)
                        }
                    )
                }
                creatingForGame = null
                userViewModel.clearGameAvailableItems()
            }
        )
    }

    val newTemplateConflict = createConflict
    if (newTemplateConflict != null) {
        LaunchedEffect(newTemplateConflict) {
            // Refresh so the clashing template is present and Overwrite can enable.
            // Deliberately unfiltered: this screen lists every game, and passing a game
            // to fetchMilestoneTemplates replaces the whole list rather than merging.
            userViewModel.fetchMilestoneTemplates()
        }
        val existingTemplate = milestoneTemplates.find {
            it.game_name == newTemplateConflict.gameName && it.name == newTemplateConflict.name
        }
        AlertDialog(
            onDismissRequest = { createConflict = null },
            title = { Text("Template Already Exists") },
            text = {
                Text("A template named \"${newTemplateConflict.name}\" already exists for ${newTemplateConflict.gameName}. Overwrite it?")
            },
            confirmButton = {
                Button(
                    enabled = existingTemplate != null,
                    onClick = {
                        existingTemplate?.let { existing ->
                            userViewModel.updateMilestoneTemplate(
                                templateId = existing.id,
                                name = newTemplateConflict.name,
                                gameName = newTemplateConflict.gameName,
                                items = newTemplateConflict.items
                            )
                        }
                        createConflict = null
                    }
                ) {
                    if (existingTemplate == null) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    } else {
                        Text("Overwrite")
                    }
                }
            },
            dismissButton = {
                TextButton(onClick = { createConflict = null }) { Text("Cancel") }
            }
        )
    }

    val toEdit = editingTemplate
    if (toEdit != null) {
        LaunchedEffect(toEdit.id) {
            userViewModel.fetchGameAvailableItems(toEdit.game_name)
        }
        val initialItems = remember(toEdit.id) {
            toEdit.items.map {
                ThresholdGroupItemRequest(
                    item_name = it.item_name,
                    quantity = it.quantity,
                    is_group = it.is_group
                )
            }
        }
        ThresholdGroupSheet(
            title = "Edit Template",
            confirmLabel = "Save",
            initialName = toEdit.name,
            initialItems = initialItems,
            availableItems = gameAvailableItems,
            isAutocompleteLoading = isGameItemsLoading,
            nameRequired = true,
            onDismiss = {
                editingTemplate = null
                userViewModel.clearGameAvailableItems()
            },
            onConfirm = { name, items, _ ->
                userViewModel.updateMilestoneTemplate(
                    templateId = toEdit.id,
                    name = name ?: toEdit.name,
                    gameName = toEdit.game_name,
                    items = items
                )
                editingTemplate = null
                userViewModel.clearGameAvailableItems()
            }
        )
    }

    val toDelete = deletingTemplate
    if (toDelete != null) {
        AlertDialog(
            onDismissRequest = { deletingTemplate = null },
            title = { Text("Delete Template?") },
            text = {
                Text("This will permanently delete \"${toDelete.name}\" for ${toDelete.game_name}.")
            },
            confirmButton = {
                TextButton(onClick = {
                    userViewModel.deleteMilestoneTemplate(toDelete.id)
                    deletingTemplate = null
                }) {
                    Text("Delete", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { deletingTemplate = null }) { Text("Cancel") }
            }
        )
    }

    if (showImportDialog) {
        ImportTemplatesDialog(
            onDismiss = { showImportDialog = false },
            onImport = { parsed ->
                importItems = parsed
                importIndex = 0
                importLog.clear()
                showImportDialog = false
            }
        )
    }

    val conflict = importConflict
    if (conflict != null) {
        LaunchedEffect(conflict) {
            userViewModel.fetchMilestoneTemplates()
        }
        val existingTemplate = milestoneTemplates.find {
            it.game_name == conflict.game && it.name == conflict.name
        }
        AlertDialog(
            onDismissRequest = { },
            title = { Text("Template Already Exists") },
            text = {
                Text(
                    "A template named \"${conflict.name}\" already exists for ${conflict.game}. " +
                        "Overwrite it, or skip importing this one?"
                )
            },
            confirmButton = {
                Button(
                    enabled = existingTemplate != null,
                    onClick = {
                        val existing = existingTemplate ?: return@Button
                        userViewModel.updateMilestoneTemplate(
                            templateId = existing.id,
                            name = conflict.name,
                            gameName = conflict.game,
                            items = conflict.items.map { ThresholdGroupItemRequest(it.itemName, it.quantity, it.isGroup) },
                            onSuccess = {
                                importLog.add("Overwrote \"${conflict.name}\" for ${conflict.game}.")
                                importConflict = null
                                importIndex += 1
                            },
                            onError = {
                                importLog.add("Failed overwriting \"${conflict.name}\" for ${conflict.game}.")
                                importConflict = null
                                importIndex += 1
                            },
                            notify = false
                        )
                    }
                ) {
                    if (existingTemplate == null) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    } else {
                        Text("Overwrite")
                    }
                }
            },
            dismissButton = {
                TextButton(onClick = {
                    importLog.add("Skipped \"${conflict.name}\" for ${conflict.game} (already exists).")
                    importConflict = null
                    importIndex += 1
                }) {
                    Text("Skip")
                }
            }
        )
    }

    if (importItems.isNotEmpty() && importIndex >= importItems.size && importConflict == null) {
        AlertDialog(
            onDismissRequest = {
                importItems = emptyList()
                importIndex = 0
                importLog.clear()
            },
            title = { Text("Import Complete") },
            text = {
                Column {
                    importLog.forEach { line ->
                        Text(line, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 2.dp))
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    importItems = emptyList()
                    importIndex = 0
                    importLog.clear()
                }) {
                    Text("Done")
                }
            }
        )
    }
}

/** Carries the details of a name clash so the overwrite prompt can act on it. */
private data class TemplateConflict(
    val items: List<ThresholdGroupItemRequest>,
    val name: String,
    val gameName: String
)

/**
 * Picks the game a new template belongs to. Item autocomplete is per-game, so the
 * choice has to come before the editor opens.
 *
 * Two sections, both searchable: the games the user actually plays sit at the top,
 * then every other game the server has a datapackage for. Building a template does
 * not need a slot, so there is no reason to limit the list to games already played.
 */
@Composable
fun GamePickerDialog(
    myGames: List<String>,
    otherGames: List<String>,
    isLoadingOtherGames: Boolean = false,
    onDismiss: () -> Unit,
    onSelect: (String) -> Unit
) {
    var query by remember { mutableStateOf("") }
    val filteredMine = remember(query, myGames) {
        if (query.isBlank()) myGames else myGames.filter { it.contains(query, ignoreCase = true) }
    }
    val filteredOthers = remember(query, otherGames) {
        if (query.isBlank()) otherGames else otherGames.filter { it.contains(query, ignoreCase = true) }
    }
    // The bulk of the list comes from the server, so reaching this state with nothing
    // to show and nothing still in flight means the fetch failed. Saying "track a slot
    // first" would contradict the toast the failure already raised.
    val noGamesAtAll = myGames.isEmpty() && otherGames.isEmpty() && !isLoadingOtherGames

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (noGamesAtAll) "Game List Unavailable" else "Choose a Game") },
        text = {
            if (noGamesAtAll) {
                Text(
                    "The list of games could not be loaded. Check your connection, then " +
                        "reopen this dialog."
                )
            } else {
                Column {
                    Text(
                        "Milestone items come from the game's datapackage, so pick the game first.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Spacer(Modifier.height(12.dp))
                    OutlinedTextField(
                        value = query,
                        onValueChange = { query = it },
                        label = { Text("Search games") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                        // The full game list comes from the server. Without this the
                        // dialog looks finished while it is still arriving.
                        trailingIcon = {
                            if (isLoadingOtherGames) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(20.dp),
                                    strokeWidth = 2.dp
                                )
                            }
                        }
                    )
                    Spacer(Modifier.height(8.dp))
                    if (isLoadingOtherGames && filteredMine.isEmpty() && filteredOthers.isEmpty()) {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(100.dp),
                            contentAlignment = Alignment.Center
                        ) {
                            CircularProgressIndicator()
                        }
                    } else if (filteredMine.isEmpty() && filteredOthers.isEmpty()) {
                        Text(
                            "No game matches that search.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(vertical = 12.dp)
                        )
                    } else {
                        LazyColumn(modifier = Modifier.heightIn(max = 320.dp)) {
                            if (filteredMine.isNotEmpty()) {
                                item(key = "header_mine") { GamePickerSectionHeader("Your games") }
                                items(filteredMine, key = { "mine_$it" }) { game ->
                                    GamePickerRow(game) { onSelect(game) }
                                }
                            }
                            if (filteredOthers.isNotEmpty()) {
                                item(key = "header_all") { GamePickerSectionHeader("All games") }
                                items(filteredOthers, key = { "all_$it" }) { game ->
                                    GamePickerRow(game) { onSelect(game) }
                                }
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text(if (noGamesAtAll) "OK" else "Cancel") }
        }
    )
}

@Composable
private fun GamePickerSectionHeader(label: String) {
    Text(
        label,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(top = 8.dp, bottom = 4.dp)
    )
}

@Composable
private fun GamePickerRow(game: String, onClick: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 12.dp)
    ) {
        Text(game, style = MaterialTheme.typography.bodyLarge)
    }
    HorizontalDivider()
}

@Composable
fun TemplatesTips() {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.small,
        color = MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.6f)
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                Icons.Default.Info,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSecondaryContainer,
                modifier = Modifier.size(20.dp)
            )
            Spacer(modifier = Modifier.width(12.dp))
            Text(
                "Tap + to build a template here, or save one from a slot's Milestone Groups " +
                    "(tap Bookmark on a group). Use the upload icon to import a template someone shared with you.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSecondaryContainer
            )
        }
    }
}

@Composable
fun ImportTemplatesDialog(
    onDismiss: () -> Unit,
    onImport: (List<ParsedTemplate>) -> Unit
) {
    var text by remember { mutableStateOf("") }
    var parseError by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Import Templates") },
        text = {
            Column {
                Text(
                    "Paste a template string shared by another player, or exported from this app.",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.Gray,
                    modifier = Modifier.padding(bottom = 12.dp)
                )
                OutlinedTextField(
                    value = text,
                    onValueChange = {
                        text = it
                        parseError = null
                    },
                    label = { Text("Template String") },
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 120.dp),
                    maxLines = 6
                )
                parseError?.let {
                    Spacer(Modifier.height(8.dp))
                    Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    when (val result = parseMilestoneTemplateShareString(text)) {
                        is TemplateImportResult.Success -> onImport(result.templates)
                        is TemplateImportResult.Failure -> parseError = result.reason
                    }
                },
                enabled = text.isNotBlank()
            ) {
                Text("Import")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        }
    )
}

@Composable
fun MilestoneTemplateCard(
    template: MilestoneTemplate,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
    onExport: () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        shape = RoundedCornerShape(16.dp)
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    template.name,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface
                )
                Spacer(Modifier.height(4.dp))
                val summary = template.items.joinToString(", ") {
                    if (it.is_group) "${it.item_name} (Group) x${it.quantity}" else "${it.item_name} x${it.quantity}"
                }
                Text(
                    summary,
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.Gray,
                    maxLines = 2
                )
            }
            IconButton(onClick = onExport) {
                Icon(Icons.Default.Share, contentDescription = "Export", tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            IconButton(onClick = onEdit) {
                Icon(Icons.Default.Edit, contentDescription = "Edit", tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            IconButton(onClick = onDelete) {
                Icon(Icons.Default.Delete, contentDescription = "Delete", tint = MaterialTheme.colorScheme.error)
            }
        }
    }
}
