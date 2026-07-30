package com.jones.aptracker.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
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
import androidx.compose.foundation.layout.imePadding
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
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
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
import com.jones.aptracker.network.WhitelistItem

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WhitelistScreen(
    userViewModel: UserViewModel = viewModel(),
    onBackClick: () -> Unit
) {
    val whitelist by userViewModel.whitelist.collectAsState()
    val knownGames by userViewModel.knownGames.collectAsState()

    var searchQuery by remember { mutableStateOf("") }
    val sortOption by userViewModel.whitelistSortOption.collectAsState()

    val processedList = remember(whitelist, searchQuery, sortOption) {
        val filtered = if (searchQuery.isBlank()) {
            whitelist
        } else {
            whitelist.filter {
                it.itemName.contains(searchQuery, ignoreCase = true) ||
                        (it.gameName?.contains(searchQuery, ignoreCase = true) == true)
            }
        }

        when (sortOption) {
            IgnoreSortOption.NEWEST -> filtered.sortedByDescending { it.id }
            IgnoreSortOption.OLDEST -> filtered.sortedBy { it.id }
            IgnoreSortOption.NAME_AZ -> filtered.sortedBy { it.itemName.lowercase() }
            IgnoreSortOption.GAME_AZ -> filtered.sortedWith(
                compareBy<WhitelistItem> { it.gameName ?: "" }.thenBy { it.itemName }
            )
        }
    }

    val selectedIds = remember { mutableStateListOf<Int>() }
    val isSelectionMode = selectedIds.isNotEmpty()

    var showSheet by remember { mutableStateOf(false) }
    var editingItem by remember { mutableStateOf<WhitelistItem?>(null) }
    var showDeleteDialog by remember { mutableStateOf(false) }
    var singleItemToDelete by remember { mutableStateOf<WhitelistItem?>(null) }

    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val haptics = LocalHapticFeedback.current

    LaunchedEffect(Unit) {
        userViewModel.fetchWhitelist()
        userViewModel.fetchKnownGames()
    }

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
                        title = { Text("Whitelisted Items") },
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
            if (whitelist.isNotEmpty() || searchQuery.isNotEmpty()) {
                SearchAndSortHeader(
                    query = searchQuery,
                    onQueryChange = { searchQuery = it },
                    currentSort = sortOption,
                    onSortChange = { userViewModel.setWhitelistSortOption(it) }
                )

                WhitelistTips()
            }

            Box(modifier = Modifier.weight(1f)) {
                if (whitelist.isEmpty()) {
                    EmptyStateView(
                        message = "No whitelisted items.",
                        subMessage = "Tap + to add a rule."
                    )
                } else if (processedList.isEmpty()) {
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

                            WhitelistItemCard(
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

    if (showDeleteDialog) {
        val count = if (singleItemToDelete != null) 1 else selectedIds.size
        AlertDialog(
            onDismissRequest = {
                showDeleteDialog = false
                singleItemToDelete = null
            },
            icon = { Icon(Icons.Default.Warning, contentDescription = null) },
            title = { Text("Delete Whitelist Rule?") },
            text = {
                Text("Are you sure you want to stop whitelisting $count item(s)? Default notification preferences will apply to them again.")
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        if (singleItemToDelete != null) {
                            userViewModel.deleteWhitelistItem(singleItemToDelete!!.id)
                        } else {
                            selectedIds.forEach { id -> userViewModel.deleteWhitelistItem(id) }
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

    if (showSheet) {
        ModalBottomSheet(
            onDismissRequest = {
                showSheet = false
                editingItem = null
            },
            sheetState = sheetState,
        ) {
            WhitelistRuleSheet(
                existingItem = editingItem,
                knownGames = knownGames,
                onDismiss = {
                    showSheet = false
                    editingItem = null
                },
                onConfirm = { itemName, gameName, isGroup ->
                    if (editingItem == null) {
                        userViewModel.addWhitelistItem(itemName, gameName, isGroup)
                    } else {
                        userViewModel.updateWhitelistItem(editingItem!!.id, itemName, gameName, isGroup)
                    }
                    showSheet = false
                    editingItem = null
                }
            )
        }
    }
}

@Composable
fun WhitelistTips() {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp),
        shape = MaterialTheme.shapes.small,
        color = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.6f)
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                Icons.Default.Info,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onPrimaryContainer,
                modifier = Modifier.size(20.dp)
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column {
                Text(
                    text = "• Whitelisted items always notify regardless of filters",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onPrimaryContainer
                )
                Text(
                    text = "• Use standard wildcards (e.g. *Key)",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onPrimaryContainer
                )
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WhitelistItemCard(
    item: WhitelistItem,
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
                Row(verticalAlignment = Alignment.CenterVertically) {
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
                    if (item.isGroup) {
                        Spacer(Modifier.width(8.dp))
                        Surface(
                            color = MaterialTheme.colorScheme.tertiaryContainer,
                            shape = MaterialTheme.shapes.small
                        ) {
                            Text(
                                text = "Group",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onTertiaryContainer,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                            )
                        }
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
fun WhitelistRuleSheet(
    existingItem: WhitelistItem?,
    knownGames: List<String>,
    onDismiss: () -> Unit,
    onConfirm: (String, String?, Boolean) -> Unit,
    userViewModel: UserViewModel = viewModel()
) {
    var itemName by remember { mutableStateOf(existingItem?.itemName ?: "") }
    var selectedTypeIndex by remember { mutableStateOf(if (existingItem?.gameName != null) 1 else 0) }
    var gameNameQuery by remember { mutableStateOf(existingItem?.gameName ?: "") }

    var selectedGame by remember { mutableStateOf<String?>(existingItem?.gameName) }
    var selectedCategory by remember { mutableStateOf(if (existingItem?.isGroup == true) 1 else 0) }
    var itemQuery by remember { mutableStateOf(existingItem?.itemName ?: "") }

    val gameAvailableItems by userViewModel.gameAvailableItems.collectAsState()
    var isItemsLoading by remember { mutableStateOf(false) }

    LaunchedEffect(selectedGame) {
        if (selectedGame != null) {
            isItemsLoading = true
            userViewModel.fetchGameAvailableItems(selectedGame!!)
        } else {
            userViewModel.clearGameAvailableItems()
            isItemsLoading = false
        }
    }

    LaunchedEffect(gameAvailableItems) {
        isItemsLoading = false
    }

    val filteredGames = remember(gameNameQuery, knownGames) {
        if (gameNameQuery.isBlank()) knownGames else knownGames.filter {
            it.contains(gameNameQuery, ignoreCase = true)
        }
    }

    val filteredItems = remember(itemQuery, gameAvailableItems, selectedCategory) {
        val targetIsGroup = (selectedCategory == 1)
        val list = gameAvailableItems.filter { it.isGroup == targetIsGroup }
        if (itemQuery.isBlank()) {
            list
        } else {
            list.filter { it.name.contains(itemQuery, ignoreCase = true) }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .navigationBarsPadding()
            .imePadding()
            .fillMaxHeight(0.85f)
    ) {
        Text(
            text = if (existingItem == null) "Add Whitelist Rule" else "Edit Whitelist Rule",
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(vertical = 16.dp)
        )

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

        if (selectedTypeIndex == 0) {
            OutlinedTextField(
                value = itemName,
                onValueChange = { itemName = it },
                label = { Text("Item Name (e.g. *Key)") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(Modifier.weight(1f))
        } else {
            if (selectedGame == null) {
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
                                    .clickable {
                                        selectedGame = game
                                        gameNameQuery = game
                                    }
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
                Card(
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer),
                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text(selectedGame!!, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                        TextButton(onClick = {
                            selectedGame = null
                            gameNameQuery = ""
                            itemName = ""
                            itemQuery = ""
                        }) {
                            Text("Change Game")
                        }
                    }
                }

                Spacer(Modifier.height(12.dp))

                Text("Whitelist Type", style = MaterialTheme.typography.labelMedium)
                Spacer(Modifier.height(4.dp))
                SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                    SegmentedButton(
                        selected = selectedCategory == 0,
                        onClick = {
                            selectedCategory = 0
                            itemName = ""
                            itemQuery = ""
                        },
                        shape = SegmentedButtonDefaults.itemShape(index = 0, count = 2)
                    ) { Text("Single Item") }

                    SegmentedButton(
                        selected = selectedCategory == 1,
                        onClick = {
                            selectedCategory = 1
                            itemName = ""
                            itemQuery = ""
                        },
                        shape = SegmentedButtonDefaults.itemShape(index = 1, count = 2)
                    ) { Text("Item Group") }
                }

                Spacer(Modifier.height(12.dp))

                OutlinedTextField(
                    value = itemQuery,
                    onValueChange = {
                        itemQuery = it
                        itemName = it
                    },
                    label = { Text(if (selectedCategory == 1) "Search or Type Group..." else "Search or Type Item...") },
                    placeholder = { Text(if (selectedCategory == 1) "e.g. Boos" else "e.g. Power Star") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    leadingIcon = { Icon(Icons.Default.Search, null) }
                )
                Spacer(Modifier.height(8.dp))

                if (isItemsLoading) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f),
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator()
                    }
                } else {
                    LazyColumn(modifier = Modifier.weight(1f)) {
                        if (filteredItems.isEmpty()) {
                            item {
                                Text(
                                    if (selectedCategory == 1) "No matching groups found." else "No matching items found.",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.padding(8.dp)
                                )
                            }
                        } else {
                            items(filteredItems) { opt ->
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clickable {
                                            itemName = opt.name
                                            itemQuery = opt.name
                                        }
                                        .padding(vertical = 12.dp, horizontal = 4.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    if (itemName.equals(opt.name, ignoreCase = true)) {
                                        Icon(Icons.Default.Check, null, modifier = Modifier.size(16.dp), tint = MaterialTheme.colorScheme.primary)
                                        Spacer(Modifier.width(8.dp))
                                    }
                                    Text(opt.name, style = MaterialTheme.typography.bodyLarge)
                                }
                                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f))
                            }
                        }
                    }
                }
            }
        }

        Spacer(Modifier.height(16.dp))

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 16.dp),
            horizontalArrangement = Arrangement.End
        ) {
            TextButton(onClick = onDismiss) {
                Text("Cancel")
            }
            Spacer(Modifier.width(8.dp))
            androidx.compose.material3.Button(
                onClick = {
                    val finalGameName = if (selectedTypeIndex == 0) null else selectedGame
                    val isGroup = (selectedTypeIndex == 1 && selectedCategory == 1)
                    onConfirm(itemName.trim(), finalGameName, isGroup)
                },
                enabled = itemName.isNotBlank() && (selectedTypeIndex == 0 || selectedGame != null)
            ) {
                Text("Save")
            }
        }
    }
}
