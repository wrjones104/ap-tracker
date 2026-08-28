package com.jones.aptracker.ui

import android.app.Application
import android.util.Log
import androidx.lifecycle.*
import com.jones.aptracker.MyFirebaseMessagingService
import com.jones.aptracker.network.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.database.CachedDatapackageEntity
import com.jones.aptracker.repository.DatapackageRepository

class TextClientViewModel : ViewModel() {

    private val _connectionStatus = MutableStateFlow(ConnectionStatus.DISCONNECTED)
    val connectionStatus = _connectionStatus.asStateFlow()

    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages = _messages.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error = _error.asStateFlow()

    private val _isAutocompleteLoading = MutableStateFlow(false)
    val isAutocompleteLoading = _isAutocompleteLoading.asStateFlow()

    private val _availableItems = MutableStateFlow<List<AutocompleteOption>>(emptyList())
    val availableItems = _availableItems.asStateFlow()

    private val _availableLocations = MutableStateFlow<List<AutocompleteOption>>(emptyList())
    val availableLocations = _availableLocations.asStateFlow()

    private val _datapackage = MutableStateFlow<RoomDatapackage?>(null)
    val datapackage = _datapackage.asStateFlow()

    private val _keepScreenOn = MutableStateFlow(false)
    val keepScreenOn = _keepScreenOn.asStateFlow()

    fun setKeepScreenOn(enabled: Boolean) {
        _keepScreenOn.value = enabled
    }

    private var wsManager: ArchipelagoWebSocketManager? = null
    private var backgroundJob: Job? = null
    private var isAppInBackground = false
    private val TAG = "TextClientVM"

    // Datapackage assembly state.
    //
    // Every field below is read and written only from viewModelScope, which runs on the
    // main dispatcher, so the websocket reader thread never races the loader coroutine.
    // The websocket callbacks hand their payloads over with a launch rather than
    // touching any of this directly.
    private var datapackageRepo: DatapackageRepository? = null
    private var connectedRoomDbId: Int? = null
    private var gameChecksums: Map<String, String> = emptyMap()
    private var playerNames: Map<String, String> = emptyMap()
    private var slotToChecksum: Map<String, String> = emptyMap()
    private var ourSlot: Int? = null
    private var genericChecksum: String? = null
    private val resolvedItems = mutableMapOf<String, String>()
    private val resolvedLocations = mutableMapOf<String, String>()
    private var datapackageJob: Job? = null

    fun connect(
        host: String,
        slotName: String,
        game: String,
        password: String?,
        roomDbId: Int? = null,
        application: Application? = null
    ) {
        wsManager?.disconnect()
        datapackageJob?.cancel()

        connectedRoomDbId = roomDbId
        if (application != null && datapackageRepo == null) {
            datapackageRepo = DatapackageRepository(application)
        }
        // Checksums are per-room and arrive fresh in RoomInfo. The resolved id tables
        // are keyed by checksum and stay valid, so only this gets reset.
        gameChecksums = emptyMap()

        wsManager = ArchipelagoWebSocketManager(
            host = host,
            slotName = slotName,
            game = game,
            password = password,
            listener = object : ArchipelagoWebSocketManager.ArchipelagoEventListener {
                override fun onStatusChanged(status: ConnectionStatus) {
                    _connectionStatus.value = status
                    if (status == ConnectionStatus.CONNECTED) {
                        _error.value = null
                    }
                }

                override fun onMessageReceived(message: ChatMessage) {
                    // Limit message history to 500 to avoid memory/performance issues
                    _messages.update { it.takeLast(499) + message }
                }

                override fun onError(error: String) {
                    _error.value = error
                }

                override fun onRoomInfo(datapackageChecksums: Map<String, String>) {
                    viewModelScope.launch { gameChecksums = datapackageChecksums }
                }

                override fun onConnected(
                    team: Int,
                    slot: Int,
                    players: List<ApNetworkPlayer>,
                    slotInfo: Map<String, ApNetworkSlot>
                ) {
                    // RoomInfo always precedes Connected on the same reader thread, so
                    // the launch above is already queued ahead of this one and
                    // gameChecksums is populated by the time this runs.
                    viewModelScope.launch { onHandshakeComplete(team, slot, players, slotInfo) }
                }
            }
        )
        wsManager?.connect()
    }

    /**
     * Turn the Archipelago handshake into everything room-specific the console needs to
     * read a PrintJSON line, then start filling in the id tables behind it.
     */
    private fun onHandshakeComplete(
        team: Int,
        slot: Int,
        players: List<ApNetworkPlayer>,
        slotInfo: Map<String, ApNetworkSlot>
    ) {
        ourSlot = slot
        playerNames = buildPlayerNames(team, players)
        slotToChecksum = buildSlotChecksums(slotInfo, gameChecksums)
        genericChecksum = gameChecksums[GENERIC_GAME]

        // Player names come entirely from the handshake, so publish before the id tables
        // land -- they resolve immediately even on a cold cache.
        publishDatapackage()

        val needed = slotToChecksum.values.toSet() + setOfNotNull(genericChecksum)
        if (needed.isEmpty()) {
            // Servers older than the datapackage_checksums field send no checksums at
            // all. Fall back to the room-scoped endpoint, which builds the same maps
            // server-side from whatever the poller cached.
            loadLegacyDatapackage()
        } else {
            loadDatapackages(needed)
        }
    }

    /**
     * Fill in the id -> name tables for [checksums], disk first.
     *
     * The cache is read and published before anything is fetched, so a room the user has
     * opened before names itself with no network at all and a room sharing games with
     * one they have opened before names most of itself instantly. Whatever is left is
     * fetched and retried with backoff. Every stage publishes what it got rather than
     * waiting for a complete set: a partial map still names most of a room, which beats
     * showing raw ids everywhere because one game was unreachable.
     */
    private fun loadDatapackages(checksums: Set<String>) {
        val repo = datapackageRepo
        if (repo == null) {
            Log.w(TAG, "No Application for the datapackage cache; using room endpoint")
            loadLegacyDatapackage()
            return
        }

        datapackageJob?.cancel()
        datapackageJob = viewModelScope.launch {
            // One query for everything already on disk, published before any request
            // goes out, so a room the user has opened before names itself with no
            // network at all.
            val cached = repo.readCache(checksums)
            absorb(cached)

            val priority = cached.missing intersect
                priorityChecksums(ourSlot, slotToChecksum, genericChecksum)
            val unresolved = fetchWithRetry(repo, priority) +
                fetchWithRetry(repo, cached.missing - priority)

            if (unresolved.isNotEmpty()) {
                // Last resort, and the reason the room-scoped endpoint is still called:
                // it predates the per-checksum one, so a backend too old to serve these
                // still answers it. This is what covers the window where the app ships
                // ahead of the server.
                Log.w(TAG, "Unresolved after retries: " + unresolved.size + "; trying room endpoint")
                mergeLegacyDatapackage()
            }
        }
    }

    /**
     * Fetch [checksums], retrying with backoff, and report what is still unresolved.
     *
     * A 404 is dropped from the retry set immediately. That is the server saying it does
     * not hold the package rather than the request going wrong, so backing off and asking
     * again would only delay the fallback -- which is the whole point when the backend is
     * simply older than this build.
     */
    private suspend fun CoroutineScope.fetchWithRetry(
        repo: DatapackageRepository,
        checksums: Set<String>
    ): Set<String> {
        if (checksums.isEmpty()) return emptySet()

        var pending = checksums
        var absent = emptySet<String>()
        var attempt = 0
        while (pending.isNotEmpty() && isActive) {
            val resolved = repo.fetch(pending)
            absorb(resolved)
            absent = absent + resolved.unavailable
            pending = resolved.missing - resolved.unavailable
            if (pending.isEmpty() || attempt >= MAX_DATAPACKAGE_RETRIES) break
            attempt++
            delay(RETRY_BASE_DELAY_MS shl (attempt - 1))
        }
        return pending + absent
    }

    /** Fold one batch of resolved names into the published datapackage. */
    private fun absorb(resolved: DatapackageRepository.Resolved) {
        if (resolved.items.isNotEmpty() || resolved.locations.isNotEmpty()) {
            resolvedItems.putAll(resolved.items)
            resolvedLocations.putAll(resolved.locations)
            publishDatapackage()
        }
    }

    /**
     * Fallback for servers that do not advertise datapackage checksums at all. Runs the
     * merge in its own job; use [mergeLegacyDatapackage] directly from inside a job that
     * is already running, since cancelling datapackageJob from within it would cancel the
     * caller.
     */
    private fun loadLegacyDatapackage() {
        datapackageJob?.cancel()
        datapackageJob = viewModelScope.launch { mergeLegacyDatapackage() }
    }

    /**
     * Merge the room-scoped datapackage into whatever is already resolved.
     *
     * Merges instead of replacing, and leaves the existing maps alone on failure -- raw
     * ids for part of a room beat wiping names that are already on screen.
     */
    private suspend fun mergeLegacyDatapackage() {
        val roomDbId = connectedRoomDbId
        if (roomDbId == null) {
            Log.w(TAG, "No room id available; console will show raw ids")
            return
        }

        try {
            val legacy = RetrofitClient.instance.getRoomDatapackage(roomDbId)
            resolvedItems.putAll(legacy.items)
            resolvedLocations.putAll(legacy.locations)
            // Player names already came from the handshake and are more current than the
            // poller cache behind this endpoint, so only the parts the handshake could
            // not supply are taken.
            if (slotToChecksum.isEmpty()) slotToChecksum = legacy.slot_to_checksum
            if (genericChecksum == null) genericChecksum = legacy.generic_checksum
            publishDatapackage()
        } catch (e: Exception) {
            Log.e(TAG, "Legacy room datapackage fetch failed", e)
        }
    }

    private fun publishDatapackage() {
        _datapackage.value = RoomDatapackage(
            players = playerNames,
            items = resolvedItems.toMap(),
            locations = resolvedLocations.toMap(),
            slot_to_checksum = slotToChecksum,
            generic_checksum = genericChecksum
        )
    }

    fun disconnect() {
        wsManager?.disconnect()
        wsManager = null
        // Stop any retry still backing off; there is nothing left on screen to name.
        datapackageJob?.cancel()
        _connectionStatus.value = ConnectionStatus.DISCONNECTED
        _messages.value = emptyList()
    }

    fun sendMessage(text: String) {
        wsManager?.sendMessage(text)
    }

    fun onAppBackgrounded() {
        if (connectionStatus.value == ConnectionStatus.CONNECTED || connectionStatus.value == ConnectionStatus.CONNECTING) {
            isAppInBackground = true
            Log.d(TAG, "App backgrounded. Starting 2-minute disconnect timer.")
            backgroundJob?.cancel()
            backgroundJob = viewModelScope.launch {
                delay(120_000) // 2 minutes
                if (isAppInBackground) {
                    Log.d(TAG, "2 minutes elapsed in background. Disconnecting console.")
                    disconnect()
                }
            }
        }
    }

    fun onAppForegrounded() {
        Log.d(TAG, "App foregrounded. Cancelling disconnect timer.")
        isAppInBackground = false
        backgroundJob?.cancel()
    }

    private var lastAutocompleteKey: String? = null

    fun fetchAutocompleteData(roomDbId: Int, slotId: Int, gameName: String? = null, application: Application? = null) {
        val key = if (!gameName.isNullOrEmpty()) "game:$gameName" else "slot:$roomDbId:$slotId"

        if (lastAutocompleteKey == key && _availableItems.value.isNotEmpty()) {
            _isAutocompleteLoading.value = false
            return
        }

        viewModelScope.launch {
            var hasCachedData = false

            if (application != null) {
                try {
                    val db = AppDatabase.getInstance(application)
                    val localCache = db.datapackageDao().getDatapackage(
                        key = key,
                        roomDbId = roomDbId,
                        slotId = slotId,
                        game = gameName
                    )
                    if (localCache != null) {
                        val type = object : TypeToken<List<AutocompleteOption>>() {}.type
                        val cachedItems: List<AutocompleteOption> = Gson().fromJson(localCache.itemsJson, type)
                        val cachedLocs: List<AutocompleteOption> = Gson().fromJson(localCache.locationsJson, type)
                        if (cachedItems.isNotEmpty()) {
                            _availableItems.value = cachedItems
                            hasCachedData = true
                        }
                        if (cachedLocs.isNotEmpty()) _availableLocations.value = cachedLocs
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Failed reading local datapackage cache", e)
                }
            }

            if (hasCachedData) {
                _isAutocompleteLoading.value = false
                lastAutocompleteKey = key
            } else {
                if (_isAutocompleteLoading.value) return@launch
                _isAutocompleteLoading.value = true
            }

            try {
                supervisorScope {
                    val itemsDeferred = async { RetrofitClient.instance.getAvailableItems(roomDbId, slotId) }
                    val locationsDeferred = async { RetrofitClient.instance.getAvailableLocations(roomDbId, slotId) }

                    val remoteItems = try { itemsDeferred.await() } catch (e: Exception) {
                        Log.e(TAG, "Items fetch failed", e)
                        emptyList()
                    }
                    val remoteLocations = try { locationsDeferred.await() } catch (e: Exception) {
                        Log.e(TAG, "Locations fetch failed", e)
                        emptyList()
                    }

                    if (remoteItems.isNotEmpty()) _availableItems.value = remoteItems
                    if (remoteLocations.isNotEmpty()) _availableLocations.value = remoteLocations
                    lastAutocompleteKey = key

                    if (application != null && (remoteItems.isNotEmpty() || remoteLocations.isNotEmpty())) {
                        val gson = Gson()
                        val itemsJson = gson.toJson(remoteItems)
                        val locsJson = gson.toJson(remoteLocations)
                        val db = AppDatabase.getInstance(application)

                        db.datapackageDao().insertDatapackage(
                            CachedDatapackageEntity(
                                cacheKey = "slot:$roomDbId:$slotId",
                                game = gameName,
                                roomDbId = roomDbId,
                                slotId = slotId,
                                itemsJson = itemsJson,
                                locationsJson = locsJson,
                                updatedAt = System.currentTimeMillis()
                            )
                        )

                        if (!gameName.isNullOrEmpty()) {
                            db.datapackageDao().insertDatapackage(
                                CachedDatapackageEntity(
                                    cacheKey = "game:$gameName",
                                    game = gameName,
                                    roomDbId = roomDbId,
                                    slotId = slotId,
                                    itemsJson = itemsJson,
                                    locationsJson = locsJson,
                                    updatedAt = System.currentTimeMillis()
                                )
                            )
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to fetch autocomplete", e)
            } finally {
                _isAutocompleteLoading.value = false
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        disconnect()
    }

    private companion object {
        /**
         * Archipelago's generic world. Its ids are legal in every game -- location -1 is
         * Cheat Console and -2 is Server -- so it is fetched alongside the room's real
         * games and used as a second chance on any lookup that misses.
         */
        const val GENERIC_GAME = "Archipelago"
        const val MAX_DATAPACKAGE_RETRIES = 3
        const val RETRY_BASE_DELAY_MS = 2000L
    }
}
