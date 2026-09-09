package com.jones.aptracker.ui

import android.app.Application
import android.util.Log
import android.widget.Toast
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.data.SettingsManager
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.network.AddRoomRequest
import com.jones.aptracker.network.AvailableCheeseRoom
import com.jones.aptracker.network.CheeseLinkRequest
import com.jones.aptracker.network.CheeseTrackerIdsRequest
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.Room
import com.jones.aptracker.network.UpdateRoomRequest
import com.jones.aptracker.network.UserProfile
import com.jones.aptracker.repository.RoomsRepository
import com.jones.aptracker.repository.UserRepository // Import this!
import kotlinx.coroutines.delay
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class RoomsViewModel(application: Application) : AndroidViewModel(application) {

    private val repository: RoomsRepository
    private val userRepository: UserRepository // Add this
    private val settingsManager = SettingsManager(application)

    private var syncJob: Job? = null
    private var lastFetchTime = 0L
    private val FETCH_COOLDOWN_MS = 10000L // 10 seconds

    private val _isSyncingCheese = MutableStateFlow(false)
    val isSyncingCheese: StateFlow<Boolean> = _isSyncingCheese.asStateFlow()

    private val _isAddingRoom = MutableStateFlow(false)
    val isAddingRoom: StateFlow<Boolean> = _isAddingRoom.asStateFlow()

    // Rooms on the user's Cheese dashboard that the app does not have. Offered,
    // never imported: Cheese proposes and the user decides. See #323.
    private val _availableCheeseRooms = MutableStateFlow<List<AvailableCheeseRoom>>(emptyList())
    val availableCheeseRooms: StateFlow<List<AvailableCheeseRoom>> = _availableCheeseRooms.asStateFlow()

    private val _isImportingCheeseRooms = MutableStateFlow(false)
    val isImportingCheeseRooms: StateFlow<Boolean> = _isImportingCheeseRooms.asStateFlow()

    /**
     * Whether the suggestions sheet should be on screen.
     *
     * Held here rather than on either screen because both tabs open the same sheet:
     * the banner on Rooms, and the Cheese card on Me. It is rendered above the tabs
     * so that asking for it never moves anybody off the screen they were reading.
     */
    private val _suggestionsRequested = MutableStateFlow(false)
    val suggestionsRequested: StateFlow<Boolean> = _suggestionsRequested.asStateFlow()

    /**
     * What the open sheet is showing, which is deliberately not [availableCheeseRooms].
     *
     * That one is the banner's, and it is rewritten by everything that touches Cheese:
     * a sync finishing, an import, a dismissal. Sharing it meant a background sync
     * could swap the list out from under someone reading it, and because the tick
     * boxes are keyed to the list, their ticks went with it -- so Add sent whatever
     * survived the swap, which was sometimes nothing.
     */
    private val _sheetRooms = MutableStateFlow<List<AvailableCheeseRoom>>(emptyList())
    val sheetRooms: StateFlow<List<AvailableCheeseRoom>> = _sheetRooms.asStateFlow()

    private val _isLoadingSuggestions = MutableStateFlow(false)
    val isLoadingSuggestions: StateFlow<Boolean> = _isLoadingSuggestions.asStateFlow()

    val isCheeseConnected = settingsManager.isCheeseConnected.stateIn(
        viewModelScope,
        SharingStarted.Eagerly,
        false
    )

    private val _rooms = MutableStateFlow<List<Room>>(emptyList())
    val rooms: StateFlow<List<Room>> = _rooms

    private val _isLoadingRooms = MutableStateFlow(false)
    val isLoading = _isLoadingRooms.asStateFlow()

    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    private val _archivedRooms = MutableStateFlow<List<Room>>(emptyList())
    val archivedRooms: StateFlow<List<Room>> = _archivedRooms.asStateFlow()

    private val _isLoadingArchived = MutableStateFlow(false)
    val isLoadingArchived = _isLoadingArchived.asStateFlow()

    init {
        val roomDao = AppDatabase.getInstance(application).roomDao()
        val api = RetrofitClient.instance
        repository = RoomsRepository(api, roomDao, application)
        userRepository = UserRepository(api)

        viewModelScope.launch {
            repository.allRooms
                .map { roomEntities -> roomEntities.map { RoomMapper.toDomain(it) } }
                .catch { e ->
                    _errorMessage.value = "Failed to load rooms from database."
                    Log.e("RoomsViewModel", "Error loading rooms from DB", e)
                }
                .collect { roomList -> _rooms.value = roomList }
        }

        fetchRooms() // Regular fetch

        // Checking Cheese on open is unconditional now that a sync cannot remove
        // anything: it reconciles claims for linked rooms and reads which
        // dashboard rooms are on offer. What to do with either is still the
        // user's call, per room. See #323.
        viewModelScope.launch {
            delay(1000)
            if (isCheeseConnected.value) {
                // Read separately from the sync, and first. The suggestions used to
                // arrive only as a side effect of a sync that finished, so a sync
                // that failed, rate-limited or outran its poll budget left the offer
                // invisible with no way to ask for it again.
                fetchAvailableCheeseRooms()
                triggerBackgroundSync()
            }
        }
    }

    fun reorderRooms(fromIndex: Int, toIndex: Int) {
        val currentList = _rooms.value.toMutableList()
        if (fromIndex == toIndex || fromIndex !in currentList.indices || toIndex !in currentList.indices) return

        val item = currentList.removeAt(fromIndex)
        currentList.add(toIndex, item)
        _rooms.value = currentList.toList()

        viewModelScope.launch {
            val updatedEntities = RoomMapper.toEntityList(currentList)
            repository.updateRoomOrder(updatedEntities)
        }
    }

    fun fetchRooms(force: Boolean = false) {
        if (_isLoadingRooms.value) return
        val now = System.currentTimeMillis()
        if (!force && now - lastFetchTime < FETCH_COOLDOWN_MS) {
            Log.d("RoomsViewModel", "fetchRooms: Cooldown active, skipping fetch.")
            return
        }
        _isLoadingRooms.value = true
        viewModelScope.launch {
            try {
                repository.refreshRooms()
                lastFetchTime = System.currentTimeMillis()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to refresh rooms. Check connection."
                e.printStackTrace()
            } finally {
                _isLoadingRooms.value = false
            }
        }
    }

    fun addRoom(
        roomUrl: String,
        alias: String,
        iconName: String,
        syncToCheese: Boolean?,
        onSuccess: () -> Unit
    ) {
        viewModelScope.launch {
            _isAddingRoom.value = true
            _errorMessage.value = null
            var cleanUrl = roomUrl.trim()
            if (cleanUrl.isNotEmpty() && !cleanUrl.startsWith("http://") && !cleanUrl.startsWith("https://")) {
                cleanUrl = "https://$cleanUrl"
            }

            try {
                val request = AddRoomRequest(
                    room_url = cleanUrl,
                    alias = alias,
                    icon_name = iconName,
                    sync_to_cheese = syncToCheese
                )

                // FIXED: Use Repository method we just added
                repository.addRoom(request)
                onSuccess()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to add room. Check connection."
                e.printStackTrace()
            } finally {
                _isAddingRoom.value = false
            }
        }
    }

    fun deleteRoom(roomId: Int) {
        viewModelScope.launch {
            try {
                RetrofitClient.instance.deleteRoom(roomId)
                repository.refreshRooms()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to delete room."
                e.printStackTrace()
            }
        }
    }

    fun reviveRoom(roomId: Int) {
        viewModelScope.launch {
            try {
                repository.reviveRoom(roomId)
            } catch (e: Exception) {
                _errorMessage.value = "Failed to revive room."
                e.printStackTrace()
            }
        }
    }

    fun updateRoom(roomId: Int, newAlias: String, iconName: String) {
        viewModelScope.launch {
            try {
                val request = UpdateRoomRequest(alias = newAlias, icon_name = iconName, is_archived = null)
                RetrofitClient.instance.updateRoom(roomId, request)
                repository.refreshRooms()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to update room."
                e.printStackTrace()
            }
        }
    }

    fun fetchArchivedRooms() {
        _isLoadingArchived.value = true
        viewModelScope.launch {
            try {
                // FIXED: Use Repository method we just added
                val result = repository.refreshArchivedRooms()
                _archivedRooms.value = result
            } catch (e: Exception) {
                _errorMessage.value = "Failed to load archived rooms."
                e.printStackTrace()
            } finally {
                _isLoadingArchived.value = false
            }
        }
    }

    fun archiveRoom(roomId: Int) {
        viewModelScope.launch {
            try {
                val request = UpdateRoomRequest(is_archived = true)
                RetrofitClient.instance.updateRoom(roomId, request)
                repository.refreshRooms()
                fetchArchivedRooms()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to archive room."
                e.printStackTrace()
            }
        }
    }

    fun unarchiveRoom(roomId: Int) {
        viewModelScope.launch {
            try {
                val request = UpdateRoomRequest(is_archived = false)
                RetrofitClient.instance.updateRoom(roomId, request)
                repository.refreshRooms()
                fetchArchivedRooms()
            } catch (e: Exception) {
                _errorMessage.value = "Failed to restore room."
                e.printStackTrace()
            }
        }
    }

    fun clearErrorMessage() {
        _errorMessage.value = null
    }

    fun cancelBackgroundSync() {
        syncJob?.cancel()
        _isSyncingCheese.value = false
    }

    private fun triggerBackgroundSync() {
        if (_isSyncingCheese.value) return
        _isSyncingCheese.value = true

        syncJob = viewModelScope.launch {
            try {
                // 1. Tell backend to START syncing
                val response = RetrofitClient.instance.syncCheeseTracker()
                
                // Update local state if the server response contains the status
                response.is_connected?.let {
                    settingsManager.setCheeseConnected(it)
                }

                // 2. Poll until backend says "Done"
                var retries = 0
                var finishedProfile: UserProfile? = null
                while (retries < 15) { // Check for 30 seconds
                    delay(2000)
                    val currentProfile = userRepository.getUserProfile()
                    if (!currentProfile.is_syncing_cheese) {
                        finishedProfile = currentProfile
                        break // Sync complete
                    }
                    retries++
                }

                fetchRooms(force = true)
                fetchAvailableCheeseRooms()

                // A sync that changes anything says so. It cannot remove a room
                // any more, but it can still move a slot from Playing to
                // Watching, and it can notice that a room has left the user's
                // Cheese dashboard.
                val demoted = finishedProfile?.cheese_last_sync_demoted ?: 0
                val unlisted = finishedProfile?.cheese_last_sync_unlisted ?: 0
                val parts = mutableListOf<String>()
                if (demoted > 0) {
                    // "aren't claimed by you", not "claimed by someone else":
                    // the sync also demotes slots that are simply unclaimed.
                    val slotWord = if (demoted == 1) "slot isn't" else "slots aren't"
                    parts += "$demoted $slotWord claimed by you on Cheese Tracker - " +
                        "switched to Watching. You'll still get alerts."
                }
                if (unlisted > 0) {
                    val roomWord = if (unlisted == 1) "room is" else "rooms are"
                    parts += "$unlisted $roomWord no longer on your Cheese dashboard. " +
                        "They're still here."
                }
                val message = when {
                    // The poll budget ran out with the server still working. Saying it
                    // finished would be a guess, and the counts above are all zero
                    // because no profile came back, not because nothing changed.
                    finishedProfile == null -> "Cheese Tracker is still syncing. Pull to refresh in a moment."
                    parts.isEmpty() -> "Cheese Sync Complete!"
                    else -> "Cheese Sync Complete! " + parts.joinToString(" ")
                }
                val duration = if (parts.isEmpty()) Toast.LENGTH_SHORT else Toast.LENGTH_LONG
                Toast.makeText(getApplication(), message, duration).show()

            } catch (e: kotlinx.coroutines.CancellationException) {
                Log.i("RoomsViewModel", "Background sync cancelled by user.")
                throw e
            } catch (e: Exception) {
                e.printStackTrace()
                Log.w("RoomsViewModel", "Background sync failed: ${e.message}")
                // Cheese failing is not a reason to leave the room list stale, or to
                // hide an offer the separate, cheaper call can still answer.
                fetchRooms(force = true)
                fetchAvailableCheeseRooms()
                _errorMessage.value = "Background sync failed."
            } finally {
                _isSyncingCheese.value = false
            }
        }
    }

    /**
     * Ask the server which Cheese rooms the app does not have.
     *
     * One request to Cheese, no per-tracker detail, so it is cheap enough to run
     * on open. Failures are silent: a suggestion badge is not worth an error.
     */
    fun fetchAvailableCheeseRooms(includeDismissed: Boolean = false) {
        viewModelScope.launch {
            if (!isCheeseConnected.value) {
                _availableCheeseRooms.value = emptyList()
                return@launch
            }
            try {
                _availableCheeseRooms.value =
                    RetrofitClient.instance.getAvailableCheeseRooms(includeDismissed).available
            } catch (e: Exception) {
                // Emptied rather than left alone. Holding the last list meant a
                // disconnect left a banner offering rooms from an account the app
                // no longer has a key for, and every later fetch failed the same
                // way, so it never cleared.
                _availableCheeseRooms.value = emptyList()
                Log.d("RoomsViewModel", "Could not read Cheese suggestions: ${e.message}")
            }
        }
    }

    /**
     * Accept suggestions: the only path that puts a Cheese room in the library.
     *
     * The sheet stays up for the duration on purpose. Each room costs a call to
     * Cheese Tracker that can take ten seconds to time out, and closing on the tap
     * left that running behind an interface with nothing to show for it -- so the
     * rooms did not appear, and the obvious response was to go and ask again.
     */
    fun importCheeseRooms(trackerIds: List<String>) {
        if (trackerIds.isEmpty()) return
        viewModelScope.launch {
            _isImportingCheeseRooms.value = true
            try {
                val result = RetrofitClient.instance.importCheeseRooms(
                    CheeseTrackerIdsRequest(trackerIds)
                )
                consumeSuggestionsRequest()
                fetchRooms(force = true)
                fetchAvailableCheeseRooms()

                // A room Cheese would not hand over is reported, not swallowed. The
                // count alone read as success when half the request had failed.
                val failed = result.failed.size
                val roomWord = if (result.imported == 1) "room" else "rooms"
                val message = if (failed > 0) {
                    val failedWord = if (failed == 1) "room" else "rooms"
                    "Added ${result.imported} $roomWord. Cheese Tracker didn't answer " +
                        "for $failed more $failedWord -- try those again."
                } else {
                    "Added ${result.imported} $roomWord from Cheese Tracker."
                }
                Toast.makeText(
                    getApplication(),
                    message,
                    if (failed > 0) Toast.LENGTH_LONG else Toast.LENGTH_SHORT
                ).show()
            } catch (e: Exception) {
                e.printStackTrace()
                consumeSuggestionsRequest()
                _errorMessage.value = "Couldn't add those rooms. Check connection."
            } finally {
                _isImportingCheeseRooms.value = false
            }
        }
    }

    /**
     * Ask for the suggestions sheet.
     *
     * [includeDismissed] is what separates the two doors into it. The banner offers
     * what is new, so it asks for that alone; the Me tab is the way back for someone
     * who hid a room or backed out of the sheet, so it asks for everything.
     */
    fun openCheeseSuggestions(includeDismissed: Boolean = true) {
        _suggestionsRequested.value = true
        _isLoadingSuggestions.value = true
        viewModelScope.launch {
            try {
                _sheetRooms.value = RetrofitClient.instance
                    .getAvailableCheeseRooms(includeDismissed).available
            } catch (e: Exception) {
                _sheetRooms.value = emptyList()
                _errorMessage.value = "Couldn't read your Cheese dashboard."
                Log.d("RoomsViewModel", "Could not read Cheese suggestions: ${e.message}")
            } finally {
                _isLoadingSuggestions.value = false
            }
        }
    }

    fun consumeSuggestionsRequest() {
        _suggestionsRequested.value = false
        _sheetRooms.value = emptyList()
    }

    /** Stop offering these. Reversible: adding one later clears the dismissal. */
    fun dismissCheeseRooms(trackerIds: List<String>) {
        if (trackerIds.isEmpty()) return
        viewModelScope.launch {
            try {
                RetrofitClient.instance.dismissCheeseRooms(CheeseTrackerIdsRequest(trackerIds))
                fetchAvailableCheeseRooms()
            } catch (e: Exception) {
                e.printStackTrace()
                _errorMessage.value = "Couldn't dismiss those. Check connection."
            }
        }
    }

    /**
     * Start or stop mirroring one room to Cheese Tracker.
     *
     * Unlinking is local: it leaves the Cheese tracker and any slot claims
     * alone, and never removes the room from the app.
     */
    fun setRoomCheeseLink(roomId: Int, linked: Boolean) {
        viewModelScope.launch {
            try {
                val result = RetrofitClient.instance.updateRoomCheeseLink(
                    roomId, CheeseLinkRequest(linked)
                )
                fetchRooms(force = true)
                val message = when {
                    result.pushing -> "Creating this room on Cheese Tracker. Takes a minute or two."
                    linked -> "Syncing this room to Cheese Tracker."
                    else -> "This room is no longer synced to Cheese Tracker. " +
                        "Your slot claims there are unchanged."
                }
                Toast.makeText(getApplication(), message, Toast.LENGTH_LONG).show()
            } catch (e: Exception) {
                e.printStackTrace()
                _errorMessage.value = "Couldn't change Cheese syncing for this room."
            }
        }
    }

    /**
     * Pull to refresh.
     *
     * The room list is ours and refreshes first, always. It used to be routed through
     * the Cheese sync, so a Cheese outage, a rate limit or a sync already running left
     * the user pulling on stale Archipelago data with nothing to show for it.
     */
    fun refreshAll(isCheeseConnected: Boolean) {
        fetchRooms(force = true)
        if (isCheeseConnected && !_isSyncingCheese.value) {
            triggerBackgroundSync()
        }
    }
}