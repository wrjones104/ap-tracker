package com.jones.aptracker.repository

import android.app.Application
import android.util.Log
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.jones.aptracker.database.AppDatabase
import com.jones.aptracker.database.CachedGameDatapackageEntity
import com.jones.aptracker.network.GameDatapackage
import com.jones.aptracker.network.RetrofitClient
import com.jones.aptracker.network.datapackageKey
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import retrofit2.HttpException

/**
 * Supplies Archipelago datapackages -- the item and location id -> name tables -- for a
 * set of game checksums.
 *
 * Archipelago addresses each game's tables by a content hash, so a package fetched once
 * is correct forever and needs no expiry or revalidation. Reading the disk and going to
 * the network are deliberately separate calls rather than one combined step: a room with
 * nine cached games and one new one should show nine games' worth of names immediately
 * instead of waiting on the tenth.
 */
class DatapackageRepository(application: Application) {

    private val dao = AppDatabase.getInstance(application).gameDatapackageDao()
    private val gson = Gson()
    private val mapType = object : TypeToken<Map<String, String>>() {}.type

    /**
     * Names keyed "<checksum>_<id>", so a caller can resolve an id knowing only the
     * checksum of the slot that owns it.
     *
     * [missing] is the checksums this call could not supply. It is not an error -- the
     * maps returned alongside it are still usable -- it just says what is left to do.
     */
    data class Resolved(
        val items: Map<String, String>,
        val locations: Map<String, String>,
        val missing: Set<String>,
        /**
         * The subset of [missing] the server answered 404 for. That is the server
         * saying it does not hold the package, not that the request went wrong, so
         * asking again on a backoff only delays whatever the caller does instead.
         */
        val unavailable: Set<String> = emptySet()
    )

    /** What one checksum's fetch turned into. */
    private sealed interface FetchResult {
        val checksum: String

        data class Ok(override val checksum: String, val pkg: GameDatapackage) : FetchResult

        /** The server has no package here (404). Retrying will not change that. */
        data class Absent(override val checksum: String) : FetchResult

        /** Went wrong in transit. Worth another attempt. */
        data class Failed(override val checksum: String) : FetchResult
    }

    /**
     * Whatever is already on device. Never touches the network, so a room the user has
     * opened before resolves with no request at all.
     */
    suspend fun readCache(checksums: Set<String>): Resolved = withContext(Dispatchers.IO) {
        if (checksums.isEmpty()) return@withContext EMPTY

        val items = HashMap<String, String>()
        val locations = HashMap<String, String>()
        val found = HashSet<String>()

        val cached = try {
            dao.getByChecksums(checksums.toList())
        } catch (e: Exception) {
            Log.e(TAG, "Failed reading cached datapackages", e)
            emptyList()
        }
        for (entity in cached) {
            // A row that will not parse is treated as absent rather than as resolved.
            // Nothing expires these rows and the checksum is the primary key, so
            // counting a corrupt one as done would leave that game showing raw ids on
            // this device forever. Leaving it missing sends it back through fetch,
            // which overwrites the bad row.
            if (merge(entity.checksum, entity.itemsJson, entity.locationsJson, items, locations)) {
                found.add(entity.checksum)
            }
        }

        Resolved(items, locations, checksums - found)
    }

    /**
     * Fetch [checksums] from the backend and write them to the cache.
     *
     * Individual failures are collected into [Resolved.missing] rather than thrown: one
     * unreachable game should not cost the caller the packages that did arrive.
     */
    suspend fun fetch(checksums: Set<String>): Resolved = withContext(Dispatchers.IO) {
        if (checksums.isEmpty()) return@withContext EMPTY

        val items = HashMap<String, String>()
        val locations = HashMap<String, String>()
        val found = HashSet<String>()

        // A large multiworld can hold dozens of distinct games. Fetch them together but
        // capped, so a first connect does not open one request per game at once.
        val gate = Semaphore(MAX_CONCURRENT_FETCHES)
        val results = coroutineScope {
            checksums.map { checksum ->
                async {
                    gate.withPermit {
                        try {
                            FetchResult.Ok(
                                checksum,
                                RetrofitClient.instance.getChecksumDatapackage(checksum)
                            )
                        } catch (e: HttpException) {
                            if (e.code() == HTTP_NOT_FOUND) {
                                Log.w(TAG, "Backend has no datapackage for $checksum")
                                FetchResult.Absent(checksum)
                            } else {
                                Log.w(TAG, "Datapackage fetch failed for $checksum: ${e.message}")
                                FetchResult.Failed(checksum)
                            }
                        } catch (e: Exception) {
                            Log.w(TAG, "Datapackage fetch failed for $checksum: ${e.message}")
                            FetchResult.Failed(checksum)
                        }
                    }
                }
            }.awaitAll()
        }

        val unavailable = HashSet<String>()
        for (result in results) {
            when (result) {
                is FetchResult.Absent -> unavailable.add(result.checksum)
                is FetchResult.Failed -> Unit
                is FetchResult.Ok -> {
                    // File it under the checksum that was asked for, not the one echoed
                    // back, so a confused response can never shadow a good package under
                    // another key.
                    val checksum = result.checksum
                    val itemsJson = gson.toJson(result.pkg.items)
                    val locationsJson = gson.toJson(result.pkg.locations)
                    if (!merge(checksum, itemsJson, locationsJson, items, locations)) continue
                    found.add(checksum)
                    try {
                        dao.insert(
                            CachedGameDatapackageEntity(
                                checksum = checksum,
                                game = result.pkg.game,
                                itemsJson = itemsJson,
                                locationsJson = locationsJson
                            )
                        )
                    } catch (e: Exception) {
                        Log.e(TAG, "Failed caching datapackage $checksum", e)
                    }
                }
            }
        }

        Resolved(items, locations, checksums - found, unavailable)
    }

    /** Returns false if the JSON would not parse, leaving [checksum] unresolved. */
    private fun merge(
        checksum: String,
        itemsJson: String,
        locationsJson: String,
        items: MutableMap<String, String>,
        locations: MutableMap<String, String>
    ): Boolean {
        return try {
            gson.fromJson<Map<String, String>>(itemsJson, mapType)?.forEach { (id, name) ->
                items[datapackageKey(checksum, id)] = name
            }
            gson.fromJson<Map<String, String>>(locationsJson, mapType)?.forEach { (id, name) ->
                locations[datapackageKey(checksum, id)] = name
            }
            true
        } catch (e: Exception) {
            Log.e(TAG, "Malformed datapackage for $checksum", e)
            false
        }
    }

    private companion object {
        const val TAG = "DatapackageRepo"
        const val MAX_CONCURRENT_FETCHES = 4
        const val HTTP_NOT_FOUND = 404
        val EMPTY = Resolved(emptyMap(), emptyMap(), emptySet())
    }
}
