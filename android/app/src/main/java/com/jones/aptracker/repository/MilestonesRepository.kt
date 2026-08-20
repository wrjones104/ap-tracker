package com.jones.aptracker.repository

import android.content.Context
import android.util.Log
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.database.CachedMilestoneGroupEntity
import com.jones.aptracker.data.FinishedDefinitionStore
import com.jones.aptracker.data.ShowFinishedPreference
import com.jones.aptracker.database.CachedTrackedSlotEntity
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.RoomItemCount
import com.jones.aptracker.network.RoomWithTrackedSlots
import com.jones.aptracker.network.ThresholdGroupItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext

data class MilestoneItemProgress(
    val itemName: String,
    /** Count held, or [UNKNOWN_QUANTITY] when it cannot be determined on-device. */
    val quantityAcquired: Int,
    val quantityRequired: Int,
    val isGroup: Boolean = false
) {
    /** True when local progress is unknowable, i.e. an unexpanded server-side item group. */
    val isIndeterminate: Boolean = quantityAcquired == UNKNOWN_QUANTITY

    val isComplete: Boolean = !isIndeterminate && quantityAcquired >= quantityRequired

    companion object {
        const val UNKNOWN_QUANTITY = -1
    }
}

data class MilestoneGroupDisplay(
    val id: Int,
    val roomDbId: Int,
    val roomAlias: String,
    val slotId: Int,
    val slotName: String,
    val name: String,
    val isTriggered: Boolean,
    val items: List<MilestoneItemProgress>,
    val totalAcquired: Int,
    val totalRequired: Int,
    val progressRatio: Float
) {
    val isComplete: Boolean = isTriggered || (totalRequired > 0 && totalAcquired >= totalRequired)

    /**
     * True when every requirement is a server-resolved item group, so there is no local number to
     * show at all. Rendered as "Tracked on server" rather than a misleading 0/0.
     */
    val isServerTracked: Boolean = !isTriggered && totalRequired == 0 && items.isNotEmpty()
}

/**
 * Result of a local-only milestone read.
 *
 * [hasCache] is false only until the first successful cache refresh. It lets a caller distinguish
 * "nothing has been fetched yet" from "this scope really has no milestones defined", which would
 * otherwise look identical -- both produce an empty [groups].
 */
data class MilestonesSnapshot(
    val groups: List<MilestoneGroupDisplay> = emptyList(),
    val slotCount: Int = 0,
    val hasCache: Boolean = false
)

/**
 * Owns milestone data for the home screen widget.
 *
 * The split here is deliberate and load-bearing:
 *
 *  - [refreshCache] / [refreshSlot] do the network work. They are called from the sync layer and
 *    from user-initiated actions, never from a widget composition.
 *  - [loadSnapshot] is local-only (Room and nothing else) and is the single call the widget makes.
 *
 * Before this split the widget fetched `/users/me/tracked-slots` (~750 KB, ~2.7s) plus one
 * `threshold-groups` request per tracked slot, sequentially, from inside `provideGlance` and its
 * reload effect. Glance renders whatever state it has while that runs, so a freshly configured
 * widget displayed the "Setup needed" placeholder for the whole round trip.
 */
object MilestonesRepository {

    private const val TAG = "MilestonesRepository"

    /** Cap on concurrent per-slot fetches, so a user with many slots does not open a socket per slot. */
    private const val MAX_PARALLEL_SLOT_FETCHES = 6

    private const val DEFAULT_MAX_CACHE_AGE_MS = 5 * 60 * 1000L

    private const val REFRESH_PREFS = "milestone_cache_prefs"
    private const val KEY_LAST_REFRESH = "last_refresh_at"

    private val gson = Gson()
    private val itemListType = object : TypeToken<List<ThresholdGroupItem>>() {}.type

    /** Coalesces concurrent refreshes; see [refreshCache]. */
    private val refreshLock = Mutex()

    /**
     * Fetches the tracked-slot roster and every slot's milestone definitions, then writes them to
     * Room. Pass [trackedRooms] when the caller already has the roster in hand (all three sync
     * paths do) to skip the large re-fetch.
     *
     * Refreshes are coalesced, not queued: if one is already running this returns false
     * immediately rather than piling a second full fan-out on top of it. Returns true when the
     * cache was actually rewritten.
     */
    suspend fun refreshCache(
        context: Context,
        trackedRooms: List<RoomWithTrackedSlots>? = null
    ): Boolean {
        if (!refreshLock.tryLock()) {
            Log.d(TAG, "Milestone cache refresh already in progress; skipping duplicate request.")
            return false
        }
        return try {
            withContext(Dispatchers.IO) { performRefresh(context.applicationContext, trackedRooms) }
        } finally {
            refreshLock.unlock()
        }
    }

    /**
     * [refreshCache], but a no-op when the cache was refreshed within [maxAgeMs].
     *
     * This is the default path for sync-driven refreshes. Milestone *definitions* only change when
     * the user edits them (covered by [refreshSlot]) or when the server flips `is_triggered`;
     * progress on plain items is recomputed locally from history on every read. Without this gate,
     * every incoming push would pay a full per-slot fan-out for data that almost never changed.
     *
     * Item-group progress is the one thing that can only arrive with a refresh, since the server
     * counts it (see `acquired` on `ThresholdGroupItem`). It therefore lags by at most this window
     * -- in practice much less, because a push-driven sync refreshes on the way through.
     */
    suspend fun refreshCacheIfStale(
        context: Context,
        trackedRooms: List<RoomWithTrackedSlots>? = null,
        maxAgeMs: Long = DEFAULT_MAX_CACHE_AGE_MS
    ): Boolean {
        val lastRefresh = try {
            withContext(Dispatchers.IO) { readLastRefresh(context) }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to read milestone cache age; refreshing anyway", e)
            null
        }

        val isFresh = lastRefresh != null && System.currentTimeMillis() - lastRefresh < maxAgeMs
        return if (isFresh) false else refreshCache(context, trackedRooms)
    }

    /**
     * Refreshes a single slot's milestone definitions. Used after the user creates, edits, or
     * deletes a milestone group, where re-fetching the whole roster would be wasteful.
     */
    suspend fun refreshSlot(context: Context, roomDbId: Int, slotId: Int): Boolean =
        withContext(Dispatchers.IO) {
            try {
                val groups = RetrofitClient.instance.getThresholdGroups(roomDbId, slotId)
                AppDatabase.getInstance(context).milestoneCacheDao()
                    .replaceMilestoneGroupsForSlot(
                        roomDbId,
                        slotId,
                        groups.map { group ->
                            CachedMilestoneGroupEntity(
                                roomDbId = roomDbId,
                                slotId = slotId,
                                groupId = group.id,
                                name = group.name,
                                isTriggered = group.is_triggered,
                                itemsJson = gson.toJson(group.items)
                            )
                        }
                    )
                true
            } catch (e: Exception) {
                Log.e(TAG, "Failed to refresh milestones for room $roomDbId slot $slotId", e)
                false
            }
        }

    private suspend fun performRefresh(
        context: Context,
        trackedRooms: List<RoomWithTrackedSlots>?
    ): Boolean {
        return try {
            val api = RetrofitClient.instance
            val rooms = trackedRooms ?: api.getUserTrackedSlots()
            val dao = AppDatabase.getInstance(context).milestoneCacheDao()
            val now = System.currentTimeMillis()

            val slotRows = rooms.flatMap { room ->
                room.tracked_slots.map { slot ->
                    CachedTrackedSlotEntity(
                        roomDbId = room.room_db_id,
                        slotId = slot.slot_id,
                        roomAlias = room.room_alias,
                        playerName = slot.player_name,
                        playerAlias = slot.player_alias,
                        isArchived = room.is_archived,
                        isFinished = slot.is_finished,
                        hasAllChecks = slot.has_all_checks,
                        updatedAt = now
                    )
                }
            }
            dao.replaceTrackedSlots(slotRows)

            val semaphore = Semaphore(MAX_PARALLEL_SLOT_FETCHES)
            val fetched = coroutineScope {
                slotRows.map { slot ->
                    async {
                        semaphore.withPermit {
                            try {
                                slot to api.getThresholdGroups(slot.roomDbId, slot.slotId)
                            } catch (e: Exception) {
                                // Leave this slot's previously cached groups in place.
                                Log.w(
                                    TAG,
                                    "Failed to fetch milestones for room ${slot.roomDbId} slot ${slot.slotId}",
                                    e
                                )
                                null
                            }
                        }
                    }
                }.awaitAll().filterNotNull()
            }

            for ((slot, groups) in fetched) {
                dao.replaceMilestoneGroupsForSlot(
                    slot.roomDbId,
                    slot.slotId,
                    groups.map { group ->
                        CachedMilestoneGroupEntity(
                            roomDbId = slot.roomDbId,
                            slotId = slot.slotId,
                            groupId = group.id,
                            name = group.name,
                            isTriggered = group.is_triggered,
                            itemsJson = gson.toJson(group.items),
                            updatedAt = now
                        )
                    }
                )
            }

            // Drop groups belonging to rooms the user no longer tracks. Guarded against an empty
            // list, which in SQL would match nothing and leave every row behind.
            val knownRoomIds = rooms.map { it.room_db_id }
            dao.deleteMilestoneGroupsForRoomsNotIn(knownRoomIds.ifEmpty { listOf(Int.MIN_VALUE) })

            // Recorded separately from the tables themselves: MAX(updatedAt) over
            // cached_tracked_slots is null for an account with no tracked slots, which would leave
            // the widget stuck on "loading" forever instead of showing the empty state.
            writeLastRefresh(context, now)

            Log.d(TAG, "Milestone cache refreshed: ${slotRows.size} slots, ${fetched.size} fetched.")
            true
        } catch (e: Exception) {
            Log.e(TAG, "Milestone cache refresh failed", e)
            false
        }
    }

    /**
     * Reads milestone progress for a widget scope. Local only: Room and nothing else, so it is
     * safe to call from a Glance composition.
     *
     * [targetRoomId] of -1 means "all active rooms". A widget pinned to a specific room keeps
     * showing that room even if it is later archived, matching what the user picked at setup.
     */
    suspend fun loadSnapshot(context: Context, targetRoomId: Int): MilestonesSnapshot =
        withContext(Dispatchers.IO) {
            val db = AppDatabase.getInstance(context)
            val dao = db.milestoneCacheDao()
            val isAllRooms = targetRoomId == -1

            val hasCache = try {
                readLastRefresh(context) != null
            } catch (e: Exception) {
                Log.e(TAG, "Failed to read milestone cache state", e)
                return@withContext MilestonesSnapshot()
            }

            val activeRooms = try {
                db.roomDao().getAllRoomsOneShot().filter { !it.is_archived }
            } catch (e: Exception) {
                emptyList()
            }
            val activeRoomIds = activeRooms.map { it.id }.toSet()
            val roomNameMap = activeRooms.associate { it.id to it.alias }

            val cachedSlots = try {
                if (isAllRooms) dao.getAllTrackedSlots() else dao.getTrackedSlotsForRoom(targetRoomId)
            } catch (e: Exception) {
                Log.e(TAG, "Failed to read cached tracked slots", e)
                emptyList()
            }

            val roomScoped = if (isAllRooms) {
                cachedSlots.filter { it.roomDbId in activeRoomIds }
            } else {
                cachedSlots
            }

            // Hide finished slots when the user has that toggle off (issue #268). The
            // milestone widget used to ignore it entirely and kept showing progress for
            // slots the rest of the app had already hidden.
            //
            // Evaluated against the user's own definition, same as every other surface,
            // so a user on "Both" keeps seeing a goaled slot that still has items to send
            // rather than having its milestones disappear out from under them.
            val showFinished = ShowFinishedPreference.get(context)
            val targetSlots = if (showFinished) {
                roomScoped
            } else {
                val resolver = FinishedDefinitionStore.resolver(context)
                roomScoped.filterNot { slot ->
                    resolver.isFinished(
                        roomDbId = slot.roomDbId,
                        slotId = slot.slotId,
                        isGoaled = slot.isFinished,
                        hasAllChecks = slot.hasAllChecks
                    )
                }
            }

            if (targetSlots.isEmpty()) {
                return@withContext MilestonesSnapshot(hasCache = hasCache)
            }

            val cachedGroups = try {
                if (isAllRooms) dao.getAllMilestoneGroups() else dao.getMilestoneGroupsForRoom(targetRoomId)
            } catch (e: Exception) {
                Log.e(TAG, "Failed to read cached milestone groups", e)
                emptyList()
            }
            val groupsBySlot = cachedGroups.groupBy { it.roomDbId to it.slotId }

            val evaluatedGroups = mutableListOf<MilestoneGroupDisplay>()

            for ((roomDbId, slots) in targetSlots.groupBy { it.roomDbId }) {
                // Skip the per-room history tally entirely when no slot in it has milestones.
                if (slots.none { groupsBySlot.containsKey(it.roomDbId to it.slotId) }) continue

                val itemCounts = try {
                    db.historyDao().getItemCountsForRoom(roomDbId)
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to load item counts for room $roomDbId", e)
                    emptyList()
                }

                for (slot in slots) {
                    val groups = groupsBySlot[slot.roomDbId to slot.slotId].orEmpty()
                    if (groups.isEmpty()) continue

                    val roomAlias = roomNameMap[roomDbId] ?: slot.roomAlias
                    val slotName = slot.playerAlias?.takeIf { it.isNotBlank() } ?: slot.playerName
                    val countsByItem = tallyForSlot(itemCounts, slot.slotId, slot.playerName, slotName)

                    for (group in groups) {
                        evaluatedGroups += evaluateGroup(
                            group = group,
                            roomDbId = roomDbId,
                            roomAlias = roomAlias,
                            slotName = slotName,
                            countsByItem = countsByItem
                        )
                    }
                }
            }

            // Incomplete groups first, highest progress first, completed groups last.
            val sortedGroups = evaluatedGroups.sortedWith(
                compareBy<MilestoneGroupDisplay> { it.isComplete }
                    .thenByDescending { it.progressRatio }
            )

            MilestonesSnapshot(
                groups = sortedGroups,
                slotCount = targetSlots.size,
                hasCache = hasCache
            )
        }

    private fun refreshPrefs(context: Context) =
        context.applicationContext.getSharedPreferences(REFRESH_PREFS, Context.MODE_PRIVATE)

    /** Epoch millis of the last completed refresh, or null if one has never completed. */
    private fun readLastRefresh(context: Context): Long? =
        refreshPrefs(context).getLong(KEY_LAST_REFRESH, 0L).takeIf { it > 0L }

    private fun writeLastRefresh(context: Context, at: Long) {
        refreshPrefs(context).edit().putLong(KEY_LAST_REFRESH, at).apply()
    }

    /**
     * Folds a room's aggregated history tallies down to the items belonging to one slot.
     *
     * Rows synced before slot ids were recorded carry a null or -1 slot id, so those fall back to
     * matching on player name or alias, as the in-app milestone view does.
     */
    private fun tallyForSlot(
        roomCounts: List<RoomItemCount>,
        slotId: Int,
        playerName: String,
        slotName: String
    ): Map<String, Int> {
        val counts = mutableMapOf<String, Int>()
        for (row in roomCounts) {
            val matchesSlot = if (row.slotId != null && row.slotId != -1) {
                row.slotId == slotId
            } else {
                row.playerName.equals(playerName, ignoreCase = true) ||
                    row.playerAlias?.equals(slotName, ignoreCase = true) == true
            }
            if (!matchesSlot) continue

            val nameKey = row.itemName.lowercase().trim()
            counts[nameKey] = (counts[nameKey] ?: 0) + row.itemCount
        }
        return counts
    }

    private fun evaluateGroup(
        group: CachedMilestoneGroupEntity,
        roomDbId: Int,
        roomAlias: String,
        slotName: String,
        countsByItem: Map<String, Int>
    ): MilestoneGroupDisplay {
        val requirements: List<ThresholdGroupItem> = try {
            gson.fromJson(group.itemsJson, itemListType) ?: emptyList()
        } catch (e: Exception) {
            Log.e(TAG, "Failed to parse cached milestone items for group ${group.groupId}", e)
            emptyList()
        }

        val isTriggered = group.isTriggered
        var totalAcquired = 0
        var totalRequired = 0

        val itemProgressList = requirements.map { itemReq ->
            val reqQty = maxOf(itemReq.quantity, 1)

            // Item-group requirements are expanded against the datapackage server-side (see
            // threshold_service.compute_requirement_progress) and summed across every member item.
            // The client has no membership data -- /games/<game>/items exposes only an is_group
            // flag -- so the server's `acquired` count is the only source of progress for them.
            // Without it (older server, or a datapackage it could not resolve) they stay
            // indeterminate and out of the totals, resolved only by the is_triggered flag.
            if (itemReq.is_group && !isTriggered && itemReq.acquired == null) {
                return@map MilestoneItemProgress(
                    itemName = itemReq.item_name,
                    quantityAcquired = MilestoneItemProgress.UNKNOWN_QUANTITY,
                    quantityRequired = reqQty,
                    isGroup = true
                )
            }

            totalRequired += reqQty

            // Plain items take the higher of the two counts. Local history is live but lossy -- it
            // is pruned by the retention window and excludes items the user filtered out -- while
            // the server count is the one the milestone actually triggers on.
            val acquiredQty = if (isTriggered) {
                reqQty
            } else {
                val localCount = if (itemReq.is_group) {
                    0
                } else {
                    countsByItem[itemReq.item_name.lowercase().trim()] ?: 0
                }
                minOf(maxOf(localCount, itemReq.acquired ?: 0), reqQty)
            }

            if (!isTriggered) {
                totalAcquired += acquiredQty
            }

            MilestoneItemProgress(
                itemName = itemReq.item_name,
                quantityAcquired = acquiredQty,
                quantityRequired = reqQty,
                isGroup = itemReq.is_group
            )
        }

        if (isTriggered) {
            totalAcquired = totalRequired
        }

        val ratio = if (totalRequired > 0) {
            (totalAcquired.toFloat() / totalRequired.toFloat()).coerceIn(0f, 1f)
        } else 0f

        val displayName = group.name?.takeIf { it.isNotBlank() }
            ?: requirements.firstOrNull()?.let { "${it.quantity}× ${it.item_name}" }
            ?: "Milestone"

        return MilestoneGroupDisplay(
            id = group.groupId,
            roomDbId = roomDbId,
            roomAlias = roomAlias,
            slotId = group.slotId,
            slotName = slotName,
            name = displayName,
            isTriggered = isTriggered,
            items = itemProgressList,
            totalAcquired = totalAcquired,
            totalRequired = totalRequired,
            progressRatio = ratio
        )
    }
}
