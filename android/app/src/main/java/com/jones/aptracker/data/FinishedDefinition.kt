package com.jones.aptracker.data

/**
 * What "finished" means for a slot, as chosen by the user.
 *
 * This is the client twin of `evaluate_finished` in `backend/app/utils.py`. The two
 * must agree exactly: the server decides which notifications to suppress and the
 * client decides what to hide, and a user seeing a slot the server has gone quiet
 * about (or the reverse) reads as a bug either way.
 *
 * Two independent facts feed it:
 *   - **goaled** — the player reached their goal (ClientStatus 30). This is what the
 *     `is_finished` wire field has always meant and still means.
 *   - **all checks** — the slot's checked locations cover its total. The community term
 *     is used deliberately, but note it is not literally "this player did all their own
 *     checks": another player collecting raises the count too, so what it really means is
 *     that this world has nothing left to send. The [description] copy unpacks that.
 *
 * The two converge automatically when the room auto-releases on goal, and diverge
 * when release is off — which is the case this whole feature exists for.
 */
enum class FinishedDefinition(val wireValue: String, val label: String, val description: String) {
    GOAL(
        "goal",
        "Goaled",
        "The player reached their goal."
    ),
    ALL_CHECKS(
        "all_checks",
        "All checks",
        "Every location has been checked, so nothing is left to send."
    ),
    BOTH(
        "both",
        "Goaled + all checks",
        "Both must be true. Keeps release-off slots visible until they are drained."
    ),
    EITHER(
        "either",
        "Goaled or all checks",
        "Either one is enough."
    );

    companion object {
        val DEFAULT = GOAL

        /**
         * Parse a server value, falling back to [DEFAULT] for anything unrecognized.
         *
         * The fallback is deliberate and matches the server: a build that predates a
         * newly added criterion degrades to goal-only rather than crashing or hiding
         * the wrong slots, so the server can ship a new option before the app knows
         * about it.
         */
        fun fromWire(value: String?): FinishedDefinition =
            entries.firstOrNull { it.wireValue == value } ?: DEFAULT
    }

    /**
     * Whether a slot reads as finished under this definition.
     *
     * [hasAllChecks] is tri-state. Null means the server has never fetched check
     * counts for that room — a host that does not serve them, or a room that stopped
     * being polled before the facts existed. Unknown is not "false": every definition
     * degrades to goal-only rather than reporting a goaled slot as unfinished.
     */
    fun evaluate(isGoaled: Boolean, hasAllChecks: Boolean?): Boolean {
        if (hasAllChecks == null) return isGoaled
        return when (this) {
            GOAL -> isGoaled
            ALL_CHECKS -> hasAllChecks
            BOTH -> isGoaled && hasAllChecks
            EITHER -> isGoaled || hasAllChecks
        }
    }
}
