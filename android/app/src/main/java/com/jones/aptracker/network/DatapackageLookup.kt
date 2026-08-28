package com.jones.aptracker.network

/**
 * Reading Archipelago identifiers off the wire.
 *
 * PrintJSON sends players, items and locations as bare numbers. Turning those back into
 * names needs three separate facts, and the rules for each are easy to get subtly wrong,
 * so they live here as pure functions rather than inline in the console screen:
 *
 *  - a slot number only means something within one team,
 *  - an item or location id only means something within one game's datapackage,
 *  - and the generic "Archipelago" world's ids are legal inside every other game.
 */

/** Checksum key for one entity id inside one game's datapackage. */
fun datapackageKey(checksum: String, id: String): String = "${checksum}_$id"

/**
 * Player slot number -> display name, for the connecting client's own [team].
 *
 * Slot numbers restart at 1 for every team, so a two-team room has two different players
 * at slot 1. Including both would leave whichever came last in the list, naming roughly
 * half the room wrongly, which is worse than the raw number it replaced. Slot 0 is the
 * server itself and never appears in [players].
 *
 * `alias` is the player's name in current time and `name` the one fixed at generation,
 * so alias wins wherever it is set.
 */
fun buildPlayerNames(team: Int, players: List<ApNetworkPlayer>): Map<String, String> {
    val names = mutableMapOf("0" to "Archipelago")
    for (player in players) {
        if (player.team != team) continue
        names[player.slot.toString()] = player.alias?.takeIf { it.isNotBlank() }
            ?: player.name?.takeIf { it.isNotBlank() }
            ?: "Player ${player.slot}"
    }
    return names
}

/**
 * Slot number -> the datapackage checksum its ids belong to.
 *
 * Two games can hand out the same id for entirely different things, so an id is only
 * resolvable once you know which game the slot plays. Slots whose game is absent from
 * [gameChecksums] are dropped rather than guessed: showing the raw number beats showing
 * another game's item name.
 */
fun buildSlotChecksums(
    slotInfo: Map<String, ApNetworkSlot>,
    gameChecksums: Map<String, String>
): Map<String, String> {
    val checksums = mutableMapOf<String, String>()
    for ((slot, info) in slotInfo) {
        val checksum = info.game?.let { gameChecksums[it] } ?: continue
        checksums[slot] = checksum
    }
    return checksums
}

/**
 * The checksums worth fetching before all the others.
 *
 * A thirty-game async needs thirty packages, fetched a few at a time, and every batch
 * that lands makes more of the console readable. The connecting player's own game names
 * most of what their own lines refer to, and the generic world covers Cheat Console and
 * Server, so those two go first rather than landing last by accident -- the fetch set is
 * otherwise unordered.
 */
fun priorityChecksums(
    ourSlot: Int?,
    slotToChecksum: Map<String, String>,
    genericChecksum: String?
): Set<String> = setOfNotNull(
    ourSlot?.let { slotToChecksum[it.toString()] },
    genericChecksum
)

/**
 * Look up one item or location name, falling back to Archipelago's generic world.
 *
 * The slot's own [checksum] is tried first. Generic ids -- location -1 is Cheat Console,
 * -2 is Server -- are valid in every world and live in a package of their own, so they
 * are the second chance. Returns [id] unchanged when neither table knows it, which keeps
 * the raw number on screen rather than dropping the segment entirely.
 */
fun resolveEntityName(
    names: Map<String, String>,
    checksum: String,
    genericChecksum: String?,
    id: String
): String {
    names[datapackageKey(checksum, id)]?.let { return it }
    if (genericChecksum != null) {
        names[datapackageKey(genericChecksum, id)]?.let { return it }
    }
    return id
}
