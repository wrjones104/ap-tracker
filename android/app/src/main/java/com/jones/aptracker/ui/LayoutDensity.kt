package com.jones.aptracker.ui

import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * How much breathing room the room list gives itself.
 *
 * This exists because the same screen has two audiences pulling in opposite directions.
 * Folding the slots into the room cards put more on one screen than the old split tabs
 * did, and the people who liked the airier layout and the people who want to see eight
 * rooms without scrolling cannot both be served by one set of paddings. So the paddings
 * became a setting rather than an argument.
 *
 * Deliberately two options, not a slider. A slider invites fiddling with numbers that
 * only matter in combination, and every intermediate value would need looking at.
 */
enum class LayoutDensity(val key: String, val description: String, val summary: String) {
    COMFORTABLE(
        "COMFORTABLE",
        "Comfortable",
        "Roomier spacing, easier to hit"
    ),
    COMPACT(
        "COMPACT",
        "Compact",
        "Tighter spacing, more rooms per screen"
    );

    val metrics: LayoutMetrics
        get() = when (this) {
            COMFORTABLE -> LayoutMetrics.Comfortable
            COMPACT -> LayoutMetrics.Compact
        }

    companion object {
        fun fromKey(key: String?): LayoutDensity =
            entries.firstOrNull { it.key == key } ?: COMFORTABLE
    }
}

/**
 * The dimensions a [LayoutDensity] resolves to.
 *
 * Held together in one object rather than as loose constants because they have to move as
 * a set: shrinking a card's padding without shrinking the row padding inside it just makes
 * the card look mis-measured.
 *
 * Touch targets are the constraint on how far Compact can go. [slotRowVertical] at 6dp
 * still leaves a slot row around 44dp tall with its two lines of text, which is at the
 * edge of the 48dp guidance and the reason it does not go lower. Compact is a tighter
 * layout, not a smaller one.
 */
data class LayoutMetrics(
    /** Gap between room cards. */
    val cardSpacing: Dp,
    /** Vertical padding inside a room card's header row. */
    val cardHeaderVertical: Dp,
    /** Vertical padding on one slot row. */
    val slotRowVertical: Dp,
    /** Left indent that marks a row as belonging to the room above it. */
    val slotIndent: Dp,
    /** Height of the hero banner pinned at the top of the list. */
    val bannerHeight: Dp,
    /** Size of the app mark inside the hero banner. */
    val bannerIconSize: Dp,
    /** Padding around the search field and filter row. */
    val chromeVertical: Dp,
    /** Whether there is room to spend a line on the reorder hint. */
    val showsReorderHint: Boolean
) {
    companion object {
        val Comfortable = LayoutMetrics(
            cardSpacing = 4.dp,
            cardHeaderVertical = 12.dp,
            slotRowVertical = 10.dp,
            slotIndent = 52.dp,
            bannerHeight = 84.dp,
            bannerIconSize = 56.dp,
            chromeVertical = 8.dp,
            showsReorderHint = true
        )

        val Compact = LayoutMetrics(
            cardSpacing = 2.dp,
            cardHeaderVertical = 8.dp,
            slotRowVertical = 6.dp,
            slotIndent = 40.dp,
            bannerHeight = 56.dp,
            bannerIconSize = 40.dp,
            chromeVertical = 4.dp,
            // The hint is the first thing to go: it teaches a gesture you only need to be
            // told about once, and it costs a line on every screen forever.
            showsReorderHint = false
        )
    }
}

/**
 * The active metrics, so a deeply nested row does not have to be handed them through every
 * composable in between.
 *
 * `static` because this changes only when the user changes the setting -- at which point
 * the whole list should recompose anyway.
 */
val LocalLayoutMetrics = staticCompositionLocalOf { LayoutMetrics.Comfortable }
