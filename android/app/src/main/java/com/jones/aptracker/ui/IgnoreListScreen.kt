package com.jones.aptracker.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Sort
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberModalBottomSheetState
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
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jones.aptracker.network.IgnoreItem

// Enum for Sorting Options
// NOTE: Ideally, move this to a shared 'models' file so the ViewModel can access it easily.
enum class IgnoreSortOption(val label: String) {
    NEWEST("Newest First"),
    OLDEST("Oldest First"),
    NAME_AZ("Item Name (A-Z)"),
    GAME_AZ("Game (A-Z)")
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IgnoreListScreen(
    userViewModel: UserViewModel = viewModel(),
    onBackClick: () -> Unit
) {
    val ignoreList by userViewModel.ignoreList.collectAsState()
    val knownGames by userViewModel.knownGames.collectAsState()

    // --- Search & Sort State ---
    // Search remains local (temporary filter), but Sort is now persistent via ViewModel
    var searchQuery by remember { mutableStateOf("") }
    val sortOption by userViewModel.ignoreSortOption.collectAsState()

    // --- Filter & Sort Logic ---
    val processedList = remember(ignoreList, searchQuery, sortOption) {
        val filtered = if (searchQuery.isBlank()) {
            ignoreList
        } else {
            ignoreList.filter {
                it.itemName.contains(searchQuery, ignoreCase = true) ||
                        (it.gameName?.contains(searchQuery, ignoreCase = true) == true)
            }
        }

        when (sortOption) {
            IgnoreSortOption.NEWEST -> filtered.sortedByDescending { it.id }
            IgnoreSortOption.OLDEST -> filtered.sortedBy { it.id }
            IgnoreSortOption.NAME_AZ -> filtered.sortedBy { it.itemName.lowercase() }
            IgnoreSortOption.GAME_AZ -> filtered.sortedWith(
                compareBy<IgnoreItem> { it.gameName ?: "" }.thenBy { it.itemName }
            )
        }
    }

    // --- Multi-Select State ---
    val selectedIds = remember { mutableStateListOf<Int>() }
    val isSelectionMode = selectedIds.isNotEmpty()

    // --- Dialogs & Sheet State ---
    var showSheet by remember { mutableStateOf(false) }
    var editingItem by remember { mutableStateOf<IgnoreItem?>(null) }
    var showDeleteDialog by remember { mutableStateOf(false) }
    var singleItemToDelete by remember { mutableStateOf<IgnoreItem?>(null) }

    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val haptics = LocalHapticFeedback.current

    // Fetch data on enter
    LaunchedEffect(Unit) {
        userViewModel.fetchIgnoreList()
        userViewModel.fetchKnownGames()
    }

    // Back Handler clears selection first, then handles nav
    BackHandler(enabled = isSelectionMode) {
        selectedIds.clear()
    }

    Scaffold(
        topBar = {
            AnimatedContent(
                targetState = isSelectionMode,
                transitionSpec = {
                    (fadeIn() + slideInVertically()).togetherWith(fadeOut() + slideOutVertically())
                },
                label = "TopBarAnimation"
            ) { selectionMode ->
                if (selectionMode) {
                    SelectionTopAppBar(
                        count = selectedIds.size,
                        onClear = { selectedIds.clear() },
                        onDelete = { showDeleteDialog = true }
                    )
                } else {
                    TopAppBar(
                        title = { Text("Ignored Items") },
                        navigationIcon = {
                            IconButton(onClick = onBackClick) {
                                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                            }
                        }
                    )
                }
            }
        },
        floatingActionButton = {
            if (!isSelectionMode) {
                FloatingActionButton(onClick = {
                    editingItem = null
                    showSheet = true
                }) {
                    Icon(Icons.Default.Add, contentDescription = "Add Rule")
                }
            }
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
        ) {
            // --- Search and Sort Header ---
            // Only show this when there are items or a filter is active
            if (ignoreList.isNotEmpty() || searchQuery.isNotEmpty()) {
                SearchAndSortHeader(
                    query = searchQuery,
                    onQueryChange = { searchQuery = it },
                    currentSort = sortOption,
                    onSortChange = { userViewModel.setIgnoreSortOption(it) }
                )

                // --- Tips Callout ---
                IgnoreListTips()
            }

            // --- Main List Content ---
            Box(modifier = Modifier.weight(1f)) {
                if (ignoreList.isEmpty()) {
                    // Overall Empty State
                    EmptyStateView(
                        message = "No ignored items.",
                        subMessage = "Tap + to add a rule."
                    )
                } else if (processedList.isEmpty()) {
                    // Filter Empty State
                    EmptyStateView(
                        message = "No matching results.",
                        subMessage = "Try adjusting your search."
                    )
                } else {
                    LazyColumn(
                        contentPadding = PaddingValues(16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.fillMaxSize()
                    ) {
                        items(processedList, key = { it.id }) { item ->
                            val isSelected = selectedIds.contains(item.id)

                            IgnoreItemCard(
                                item = item,
                                isSelectionMode = isSelectionMode,
                                isSelected = isSelected,
                                onClick = {
                                    if (isSelectionMode) {
                                        if (isSelected) selectedIds.remove(item.id) else selectedIds.add(item.id)
                                    } else {
                                        editingItem = item
                                        showSheet = true
                                    }
                                },
                                onLongClick = {
                                    if (!isSelectionMode) {
                                        haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                                        selectedIds.add(item.id)
                                    }
                                },
                                onDeleteSingle = {
                                    singleItemToDelete = item
                                    showDeleteDialog = true
                                }
                            )
                        }
                    }
                }
            }
        }
    }

    // --- 1. Delete Confirmation Dialog ---
    if (showDeleteDialog) {
        val count = if (singleItemToDelete != null) 1 else selectedIds.size
        AlertDialog(
            onDismissRequest = {
                showDeleteDialog = false
                singleItemToDelete = null
            },
            icon = { Icon(Icons.Default.Warning, contentDescription = null) },
            title = { Text("Delete Ignore Rule?") },
            text = {
                Text("Are you sure you want to stop ignoring $count item(s)? You may receive notifications for them again.")
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        if (singleItemToDelete != null) {
                            userViewModel.deleteIgnoreItem(singleItemToDelete!!.id)
                        } else {
                            // Bulk Delete
                            selectedIds.forEach { id -> userViewModel.deleteIgnoreItem(id) }
                            selectedIds.clear()
                        }
                        showDeleteDialog = false
                        singleItemToDelete = null
                    }
                ) {
                    Text("Delete", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = {
                    showDeleteDialog = false
                    singleItemToDelete = null
                }) {
                    Text("Cancel")
                }
            }
        )
    }

    // --- 2. Add/Edit Sheet ---
    if (showSheet) {
        ModalBottomSheet(
            onDismissRequest = {
                showSheet = false
                editingItem = null
            },
            sheetState = sheetState
        ) {
            IgnoreRuleSheet(
                existingItem = editingItem,
                knownGames = knownGames,
                onDismiss = {
                    showSheet = false
                    editingItem = null
                },
                onConfirm = { itemName, gameName ->
                    if (editingItem == null) {
                        userViewModel.addIgnoreItem(itemName, gameName)
                    } else {
                        userViewModel.updateIgnoreItem(editingItem!!.id, itemName, gameName)
                    }
                    showSheet = false
                    editingItem = null
                }
            )
        }
    }
}

// --- SUB-COMPONENTS ---

@Composable
fun IgnoreListTips() {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp),
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
            Column {
                Text(
                    text = "• Use standard wildcards (e.g. *Key)",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSecondaryContainer
                )
                Text(
                    text = "• Long-press items to multi-select",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSecondaryContainer
                )
            }
        }
    }
}

@Composable
fun SearchAndSortHeader(
    query: String,
    onQueryChange: (String) -> Unit,
    currentSort: IgnoreSortOption,
    onSortChange: (IgnoreSortOption) -> Unit
) {
    var sortMenuExpanded by remember { mutableStateOf(false) }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        OutlinedTextField(
            value = query,
            onValueChange = onQueryChange,
            modifier = Modifier.weight(1f),
            placeholder = { Text("Search items or games...") },
            leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
            trailingIcon = if (query.isNotEmpty()) {
                {
                    IconButton(onClick = { onQueryChange("") }) {
                        Icon(Icons.Default.Clear, contentDescription = "Clear")
                    }
                }
            } else null,
            singleLine = true
        )

        Box {
            IconButton(onClick = { sortMenuExpanded = true }) {
                Icon(Icons.AutoMirrored.Filled.Sort, contentDescription = "Sort")
            }
            DropdownMenu(
                expanded = sortMenuExpanded,
                onDismissRequest = { sortMenuExpanded = false }
            ) {
                IgnoreSortOption.values().forEach { option ->
                    DropdownMenuItem(
                        text = { Text(option.label) },
                        onClick = {
                            onSortChange(option)
                            sortMenuExpanded = false
                        },
                        trailingIcon = if (currentSort == option) {
                            { Icon(Icons.Default.Check, null) }
                        } else null
                    )
                }
            }
        }
    }
}

@Composable
fun EmptyStateView(message: String, subMessage: String) {
    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(message, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(subMessage, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun IgnoreItemCard(
    item: IgnoreItem,
    isSelectionMode: Boolean,
    isSelected: Boolean,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
    onDeleteSingle: () -> Unit
) {
    val cardColor = if (isSelected) {
        MaterialTheme.colorScheme.primaryContainer
    } else {
        MaterialTheme.colorScheme.surfaceContainer
    }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(
                onClick = onClick,
                onLongClick = onLongClick
            ),
        colors = CardDefaults.cardColors(containerColor = cardColor),
        elevation = CardDefaults.cardElevation(defaultElevation = if (isSelected) 4.dp else 1.dp)
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = item.itemName,
                    style = MaterialTheme.typography.titleMedium
                )
                Spacer(Modifier.height(4.dp))
                if (item.gameName != null) {
                    Surface(
                        color = if (isSelected) MaterialTheme.colorScheme.surface else MaterialTheme.colorScheme.primaryContainer,
                        shape = MaterialTheme.shapes.small
                    ) {
                        Text(
                            text = item.gameName,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                        )
                    }
                } else {
                    Surface(
                        color = if (isSelected) MaterialTheme.colorScheme.surface else MaterialTheme.colorScheme.secondaryContainer,
                        shape = MaterialTheme.shapes.small
                    ) {
                        Text(
                            text = "Global (All Games)",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSecondaryContainer,
                            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                        )
                    }
                }
            }

            if (isSelectionMode) {
                Checkbox(
                    checked = isSelected,
                    onCheckedChange = { onClick() }
                )
            } else {
                Row {
                    Icon(
                        Icons.Default.Edit,
                        contentDescription = "Edit",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(end = 16.dp)
                    )
                    IconButton(
                        onClick = onDeleteSingle,
                        modifier = Modifier.size(24.dp)
                    ) {
                        Icon(
                            Icons.Default.Delete,
                            contentDescription = "Delete",
                            tint = MaterialTheme.colorScheme.error
                        )
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SelectionTopAppBar(
    count: Int,
    onClear: () -> Unit,
    onDelete: () -> Unit
) {
    TopAppBar(
        title = {
            Text(
                text = "$count selected",
                style = MaterialTheme.typography.titleMedium
            )
        },
        navigationIcon = {
            IconButton(onClick = onClear) {
                Icon(Icons.Default.Close, contentDescription = "Clear selection")
            }
        },
        actions = {
            IconButton(onClick = onDelete) {
                Icon(
                    imageVector = Icons.Default.Delete,
                    contentDescription = "Delete selected"
                )
            }
        },
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHigh
        )
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IgnoreRuleSheet(
    existingItem: IgnoreItem?,
    knownGames: List<String>,
    onDismiss: () -> Unit,
    onConfirm: (String, String?) -> Unit
) {
    var itemName by remember { mutableStateOf(existingItem?.itemName ?: "") }
    var selectedTypeIndex by remember { mutableStateOf(if (existingItem?.gameName != null) 1 else 0) }
    var gameNameQuery by remember { mutableStateOf(existingItem?.gameName ?: "") }

    val filteredGames = remember(gameNameQuery, knownGames) {
        if (gameNameQuery.isBlank()) knownGames else knownGames.filter {
            it.contains(gameNameQuery, ignoreCase = true)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .navigationBarsPadding()
            .fillMaxHeight(0.85f)
    ) {
        Text(
            text = if (existingItem == null) "Add Ignore Rule" else "Edit Ignore Rule",
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(vertical = 16.dp)
        )

        OutlinedTextField(
            value = itemName,
            onValueChange = { itemName = it },
            label = { Text("Item Name (e.g. *Key)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(Modifier.height(16.dp))

        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
            SegmentedButton(
                selected = selectedTypeIndex == 0,
                onClick = { selectedTypeIndex = 0 },
                shape = SegmentedButtonDefaults.itemShape(index = 0, count = 2)
            ) { Text("Global") }

            SegmentedButton(
                selected = selectedTypeIndex == 1,
                onClick = { selectedTypeIndex = 1 },
                shape = SegmentedButtonDefaults.itemShape(index = 1, count = 2)
            ) { Text("Game Specific") }
        }

        Spacer(Modifier.height(16.dp))

        if (selectedTypeIndex == 1) {
            Text("Select Game", style = MaterialTheme.typography.labelMedium)
            OutlinedTextField(
                value = gameNameQuery,
                onValueChange = { gameNameQuery = it },
                placeholder = { Text("Search games...") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                leadingIcon = { Icon(Icons.Default.Search, null) }
            )
            Spacer(Modifier.height(8.dp))
            LazyColumn(modifier = Modifier.weight(1f)) {
                if (filteredGames.isEmpty()) {
                    item {
                        Text(
                            "No games found.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(8.dp)
                        )
                    }
                } else {
                    items(filteredGames) { game ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { gameNameQuery = game }
                                .padding(vertical = 12.dp, horizontal = 4.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            if (gameNameQuery.equals(game, ignoreCase = true)) {
                                Icon(Icons.Default.Check, null, modifier = Modifier.size(16.dp), tint = MaterialTheme.colorScheme.primary)
                                Spacer(Modifier.width(8.dp))
                            }
                            Text(game, style = MaterialTheme.typography.bodyLarge)
                        }
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f))
                    }
                }
            }
        } else {
            Spacer(Modifier.weight(1f))
        }

        Spacer(Modifier.height(16.dp))

        Row(
            modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp),
            horizontalArrangement = Arrangement.End
        ) {
            TextButton(onClick = onDismiss) { Text("Cancel") }
            Spacer(Modifier.width(8.dp))
            Button(
                onClick = {
                    val finalGame = if (selectedTypeIndex == 1) gameNameQuery.trim().ifBlank { null } else null
                    onConfirm(itemName.trim(), finalGame)
                },
                enabled = itemName.isNotBlank() && (selectedTypeIndex == 0 || gameNameQuery.isNotBlank())
            ) {
                Text(if (existingItem == null) "Add" else "Save")
            }
        }
    }
}