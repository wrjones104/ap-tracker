package com.jones.aptracker.ui

import android.net.Uri
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember

import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jones.aptracker.ui.TextClientViewModel
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.jones.aptracker.R

@Composable
fun AppNavigation(
    isLoggedIn: Boolean,
    isLoading: Boolean,
    onDiscordLoginClick: () -> Unit,
    onGuestLoginClick: () -> Unit,
    onLogoutClick: () -> Unit,
    onGuestUpgradeClick: () -> Unit,
    targetTab: String? = null,
    targetRoomId: Int? = null,
    onTargetTabConsumed: () -> Unit = {}
) {
    if (isLoggedIn) {
        val navController = rememberNavController()
        MainNavHost(
            navController = navController,
            onLogoutClick = onLogoutClick,
            onGuestUpgradeClick = onGuestUpgradeClick,
            targetTab = targetTab,
            targetRoomId = targetRoomId,
            onTargetTabConsumed = onTargetTabConsumed
        )
    } else {
        LoginScreen(
            isLoading = isLoading,
            onDiscordLoginClick = onDiscordLoginClick,
            onGuestLoginClick = onGuestLoginClick
        )
    }
}

@Composable
fun MainNavHost(
    navController: NavHostController,
    onLogoutClick: () -> Unit,
    onGuestUpgradeClick: () -> Unit,
    targetTab: String? = null,
    targetRoomId: Int? = null,
    onTargetTabConsumed: () -> Unit = {}
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val tokenManager = remember { com.jones.aptracker.network.TokenManager(context) }
    val scope = androidx.compose.runtime.rememberCoroutineScope()

    var showWelcomeModal by remember { mutableStateOf(tokenManager.isFirstLaunch()) }
    var showWhatsNewSheet by remember {
        val lastSeen = tokenManager.getLastSeenVersionCode()
        val currentCode = com.jones.aptracker.BuildConfig.VERSION_CODE
        mutableStateOf(!tokenManager.isFirstLaunch() && currentCode > lastSeen)
    }
    var latestReleaseInfo by remember { mutableStateOf<com.jones.aptracker.network.ReleaseInfo?>(null) }

    val historyViewModel: HistoryViewModel = viewModel()
    val userViewModel: UserViewModel = viewModel()

    // Fetch latest release info for What's New sheet if active
    androidx.compose.runtime.LaunchedEffect(showWhatsNewSheet) {
        if (showWhatsNewSheet) {
            try {
                val response = com.jones.aptracker.network.RetrofitClient.instance.getLatestRelease(com.jones.aptracker.BuildConfig.VERSION_NAME)
                latestReleaseInfo = response.release
            } catch (e: Exception) {
                // Fallback to built-in defaults if network request fails
            }
        }
    }

    // --- ONBOARDING & WHAT'S NEW MODALS ---
    if (showWelcomeModal) {
        WelcomeModal(
            onDismiss = {
                tokenManager.setWelcomeModalSeen()
                tokenManager.setLastSeenVersionCode(com.jones.aptracker.BuildConfig.VERSION_CODE)
                showWelcomeModal = false
            },
            onOpenGuide = {
                tokenManager.setWelcomeModalSeen()
                tokenManager.setLastSeenVersionCode(com.jones.aptracker.BuildConfig.VERSION_CODE)
                showWelcomeModal = false
                navController.navigate("tutorial_guide")
            }
        )
    }

    if (showWhatsNewSheet && !showWelcomeModal) {
        WhatsNewBottomSheet(
            versionName = com.jones.aptracker.BuildConfig.VERSION_NAME,
            releaseInfo = latestReleaseInfo,
            onDismiss = {
                tokenManager.setLastSeenVersionCode(com.jones.aptracker.BuildConfig.VERSION_CODE)
                showWhatsNewSheet = false
            }
        )
    }

    // Start destination is now 'home', which holds the Bottom Bar
    NavHost(navController = navController, startDestination = "home") {

        // --- THE MAIN CONTAINER (Bottom Nav) ---
        composable("home") {
            MainScreen(
                onLogoutClick = onLogoutClick,
                onGuestUpgradeClick = onGuestUpgradeClick,
                onNavigateToPlayers = { roomId, roomAlias ->
                    navController.navigate("players/$roomId/${Uri.encode(roomAlias)}")
                },
                onNavigateToIgnoreList = {
                    navController.navigate("ignore_list")
                },
                onNavigateToWhitelist = {
                    navController.navigate("whitelist")
                },
                onNavigateToMilestoneTemplates = {
                    navController.navigate("milestone_templates")
                },
                onNavigateToCredits = {
                    navController.navigate("credits")
                },
                onNavigateToSettings = { navController.navigate("settings") },
                onNavigateToGuide = { navController.navigate("tutorial_guide") },
                onShowWhatsNew = { showWhatsNewSheet = true },
                onNavigateToArchived = { navController.navigate("archived_rooms") },
                initialTab = targetTab,
                targetRoomId = targetRoomId,
                onTargetTabConsumed = onTargetTabConsumed,
                onNavigateToSlotDetail = { roomDbId, slotId ->
                    navController.navigate("slot_detail/$roomDbId/$slotId")
                },
                userViewModel = userViewModel,
                historyViewModel = historyViewModel
            )
        }

        // --- DETAIL SCREENS (Cover the Bottom Bar) ---

        composable("ignore_list") {
            IgnoreListScreen(
                userViewModel = userViewModel,
                onBackClick = { navController.popBackStack() }
            )
        }

        composable("whitelist") {
            WhitelistScreen(
                userViewModel = userViewModel,
                onBackClick = { navController.popBackStack() }
            )
        }

        composable("milestone_templates") {
            MilestoneTemplatesScreen(
                userViewModel = userViewModel,
                onBackClick = { navController.popBackStack() }
            )
        }

        composable("credits") {
            CreditsScreen(
                onBackClick = { navController.popBackStack() }
            )
        }

        composable("tutorial_guide") {
            TutorialGuideScreen(
                onBackClick = { navController.popBackStack() }
            )
        }

        composable(
            route = "players/{roomId}/{roomAlias}",
            arguments = listOf(
                navArgument("roomId") { type = NavType.IntType },
                navArgument("roomAlias") { type = NavType.StringType }
            )
        ) { backStackEntry ->
            val roomId = backStackEntry.arguments?.getInt("roomId")!!
            val roomAlias = Uri.decode(backStackEntry.arguments?.getString("roomAlias")!!)
            PlayersScreen(
                roomId = roomId,
                roomAlias = roomAlias,
                onSave = { navController.popBackStack() },
                userViewModel = userViewModel,
                historyViewModel = historyViewModel
            )
        }


        composable("settings") {
            SettingsScreen(
                onBackClick = { navController.popBackStack() },
                onNavigateToSlotOverrides = { navController.navigate("slot_overrides") },
                onNavigateToGuide = { navController.navigate("tutorial_guide") },
                onShowWhatsNew = { showWhatsNewSheet = true }
            )
        }

        composable("slot_overrides") {
            SlotOverridesScreen(
                onBackClick = { navController.popBackStack() }
            )
        }

        composable("archived_rooms") {
            ArchivedRoomsScreen(
                onBackClick = { navController.popBackStack()}
            )
        }


        composable(
            route = "slot_detail/{roomDbId}/{slotId}",
            arguments = listOf(
                navArgument("roomDbId") { type = NavType.IntType },
                navArgument("slotId") { type = NavType.IntType }
            )
        ) { backStackEntry ->
            val roomDbId = backStackEntry.arguments?.getInt("roomDbId")!!
            val slotId = backStackEntry.arguments?.getInt("slotId")!!
            val textClientViewModel: TextClientViewModel = viewModel(backStackEntry)
            SlotDetailScreen(
                roomDbId = roomDbId,
                slotId = slotId,
                userViewModel = userViewModel,
                textClientViewModel = textClientViewModel,
                onBackClick = { navController.popBackStack() },
                onNavigateToHistory = { roomId, _, query, player ->
                    historyViewModel.loadHistoryFor(roomId, query, player)
                    navController.navigate("slot_history")
                },
                onNavigateToMilestoneTemplates = {
                    navController.navigate("milestone_templates")
                }
            )
        }

        composable("slot_history") {
            ActivityFeedScreen(
                historyViewModel = historyViewModel,
                userViewModel = userViewModel,
                onNavigateToSlotDetail = { roomDbId, slotId ->
                    navController.navigate("slot_detail/$roomDbId/$slotId")
                },
                onBackClick = { navController.popBackStack() }
            )
        }
    }
}

// LoginScreen remains unchanged...
@Composable
fun LoginScreen(
    isLoading: Boolean,
    onDiscordLoginClick: () -> Unit,
    onGuestLoginClick: () -> Unit
) {
    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .safeDrawingPadding(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(0.9f)
                    .height(200.dp)
                    .clip(RoundedCornerShape(12.dp)),
                contentAlignment = Alignment.Center
            ) {
                Image(
                    painter = painterResource(id = R.drawable.bg_banner_gradient),
                    contentDescription = null,
                    modifier = Modifier.fillMaxSize(),
                    contentScale = ContentScale.Crop
                )
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(horizontal = 16.dp)
                ) {
                    Image(
                        painter = painterResource(id = R.drawable.ap_alerts_icon_3),
                        contentDescription = "AP Alerts Icon",
                        modifier = Modifier.size(80.dp)
                    )
                    Spacer(Modifier.width(16.dp))
                    Column {
                        Box {
                            Text(
                                text = "Archipelago Alerts",
                                style = MaterialTheme.typography.headlineMedium.copy(
                                    color = Color.Black,
                                    drawStyle = Stroke(width = with(androidx.compose.ui.platform.LocalDensity.current) { 2.dp.toPx() }, join = StrokeJoin.Round)
                                )
                            )
                            Text(
                                text = "Archipelago Alerts",
                                style = MaterialTheme.typography.headlineMedium.copy(
                                    color = Color.White
                                )
                            )
                        }
                        Text(
                            text = "Please log in below",
                            style = MaterialTheme.typography.bodyLarge,
                            color = Color.White
                        )
                    }
                }
            }
            Spacer(modifier = Modifier.height(32.dp))
            Spacer(modifier = Modifier.height(16.dp))
            if (isLoading) {
                CircularProgressIndicator()
            } else {
                Button(onClick = onDiscordLoginClick) {
                    Text("Login with Discord")
                }
                Spacer(modifier = Modifier.height(8.dp))
                TextButton(onClick = onGuestLoginClick) {
                    Text("Continue as Guest")
                }
            }
        }
    }
}