package com.jones.aptracker.ui

import com.jones.aptracker.network.HintEntity

data class ClassifiedHints(
    val forYou: List<HintEntity>,
    val byYou: List<HintEntity>
)

/**
 * Splits hints into "for you" and "by you" from the slots tracked now, keyed by
 * (room db id, slot id), by the server's rule: a hint is for you when its item's owner is
 * tracked, otherwise by you when its location's owner is. A hint touching no tracked slot
 * goes in neither list.
 *
 * Done here rather than trusting the type stored with each hint, because that type was decided
 * when the hint arrived, against whatever was tracked then. The full hint download used to
 * re-file every hint on each sync and hid that; since #411 it no longer runs on every sync.
 * Each returned hint carries the derived type, since the History screen reads `hintType`.
 */
fun classifyHints(hints: List<HintEntity>, trackedSlots: Set<Pair<Int, Int>>): ClassifiedHints {
    val forYou = mutableListOf<HintEntity>()
    val byYou = mutableListOf<HintEntity>()
    for (hint in hints) {
        when {
            (hint.roomDbId to hint.itemOwnerId) in trackedSlots ->
                forYou += if (hint.hintType == "for_you") hint else hint.copy(hintType = "for_you")
            (hint.roomDbId to hint.locationOwnerId) in trackedSlots ->
                byYou += if (hint.hintType == "by_you") hint else hint.copy(hintType = "by_you")
        }
    }
    return ClassifiedHints(forYou, byYou)
}
