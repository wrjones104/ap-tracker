package com.jones.aptracker.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jones.aptracker.network.IgnoreItem

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IgnoreListScreen(
    userViewModel: UserViewModel = viewModel(),
    onBackClick: () -> Unit
) {
    val ignoreList by userViewModel.ignoreList.collectAsState()
    val knownGames by userViewModel.knownGames.collectAsState()

    // Sheet State
    var showSheet by remember { mutableStateOf(false) }
    var editingItem by remember { mutableStateOf<IgnoreItem?>(null) } // null = Adding, non-null = Editing
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    // Fetch data on enter
    LaunchedEffect(Unit) {
        userViewModel.fetchIgnoreList()
        userViewModel.fetchKnownGames()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Ignored Items") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = {
                editingItem = null // Reset to "Add" mode
                showSheet = true
            }) {
                Icon(Icons.Default.Add, contentDescription = "Add Rule")
            }
        }
    ) { padding ->
        Box(modifier = Modifier.padding(padding).fillMaxSize()) {
            if (ignoreList.isEmpty()) {
                Column(
                    modifier = Modifier.align(Alignment.Center),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text("No ignored items.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text("Tap + to add a rule.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else {
                LazyColumn(
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxSize()
                ) {
                    item {
                        Text(
                            "These items will appear in your history but will NOT send push notifications.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(bottom = 8.dp)
                        )
                    }
                    items(ignoreList, key = { it.id }) { item ->
                        IgnoreItemCard(
                            item = item,
                            onClick = {
                                editingItem = item // Enter "Edit" mode
                                showSheet = true
                            },
                            onDelete = { userViewModel.deleteIgnoreItem(item.id) }
                        )
                    }
                }
            }
        }
    }

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
                        // Create New
                        userViewModel.addIgnoreItem(itemName, gameName)
                    } else {
                        // Update Existing
                        userViewModel.updateIgnoreItem(editingItem!!.id, itemName, gameName)
                    }
                    showSheet = false
                    editingItem = null
                }
            )
        }
    }
}

@Composable
fun IgnoreItemCard(
    item: IgnoreItem,
    onClick: () -> Unit,
    onDelete: () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
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
                        color = MaterialTheme.colorScheme.primaryContainer,
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
                        color = MaterialTheme.colorScheme.secondaryContainer,
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
            Icon(
                Icons.Default.Edit,
                contentDescription = "Edit",
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(end = 16.dp)
            )
            IconButton(onClick = onDelete) {
                Icon(Icons.Default.Delete, contentDescription = "Delete", tint = MaterialTheme.colorScheme.error)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IgnoreRuleSheet(
    existingItem: IgnoreItem?,
    knownGames: List<String>,
    onDismiss: () -> Unit,
    onConfirm: (String, String?) -> Unit
) {
    // Form State
    var itemName by remember { mutableStateOf(existingItem?.itemName ?: "") }

    // Toggle: 0 = Global, 1 = Specific
    var selectedTypeIndex by remember { mutableStateOf(if (existingItem?.gameName != null) 1 else 0) }
    var gameNameQuery by remember { mutableStateOf(existingItem?.gameName ?: "") }

    // Filter Logic
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
            .fillMaxHeight(0.85f) // Tall sheet for better scrolling
    ) {
        Text(
            text = if (existingItem == null) "Add Ignore Rule" else "Edit Ignore Rule",
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(vertical = 16.dp)
        )

        // 1. Item Name Input
        OutlinedTextField(
            value = itemName,
            onValueChange = { itemName = it },
            label = { Text("Item Name (e.g. *Key)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(Modifier.height(16.dp))

        // 2. Scope Toggle
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

        // 3. Game Search (Visible only when 'Game Specific' is selected)
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

            // Embedded Scrollable List (Better than dropdown for forms)
            LazyColumn(
                modifier = Modifier.weight(1f)
            ) {
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
                                .clickable { gameNameQuery = game } // Auto-fill on click
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
            Spacer(Modifier.weight(1f)) // Push buttons to bottom if Global mode
        }

        Spacer(Modifier.height(16.dp))

        // 4. Action Buttons
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