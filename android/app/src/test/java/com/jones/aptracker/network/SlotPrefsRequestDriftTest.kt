package com.jones.aptracker.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Guards [toPrefsRequest] against silently dropping a preference.
 *
 * The slot-preferences endpoint is a full-state write, not a patch: Retrofit runs with
 * `serializeNulls()` and the server keys off field *presence*, so a field the builder
 * forgets to copy still arrives as an explicit null and clears that slot's override.
 * Eight of [UpdateSlotPrefsRequest]'s parameters carry `= null` defaults, which means
 * forgetting one compiles clean and fails only against a real account. That is exactly
 * how "copy settings to all slots" wiped `suppress_connected` on every target slot
 * (issue #261).
 *
 * The check pairs the two classes by field name through reflection instead of restating
 * the list. Restating it would reproduce the original bug in the test: a preference added
 * to the request and missed in the builder would also be missed here.
 */
class SlotPrefsRequestDriftTest {

    /**
     * A slot with every preference set to a value distinguishable from the null an
     * unassigned constructor parameter would take. The non-preference fields are filler.
     */
    private fun slotWithEveryPreferenceSet() = TrackedSlotDetail(
        slot_id = 1,
        player_name = "Player",
        player_alias = null,
        notify_progression = true,
        notify_useful = true,
        notify_filler = true,
        notify_trap = true,
        notify_hints = true,
        notify_hints_remote_items = true,
        combine_notifications = true,
        suppress_own_events = true,
        remove_emojis = true,
        suppress_self_found = true,
        notify_finished = true,
        use_condensed_messages = true,
        suppress_connected = true,
        finished_definition = "all_checks"
    )

    @Test
    fun `every request field is copied from the matching slot field`() {
        val slot = slotWithEveryPreferenceSet()
        val request = slot.toPrefsRequest()

        val requestFields = UpdateSlotPrefsRequest::class.java.declaredFields
            .filterNot { it.isSynthetic }

        // Without this the test passes vacuously if the class is ever emptied or the
        // field list stops being reflectable.
        assertTrue(
            "Expected UpdateSlotPrefsRequest to declare preference fields, found none",
            requestFields.size >= 14
        )

        for (field in requestFields) {
            val name = field.name

            val sourceField = runCatching {
                TrackedSlotDetail::class.java.getDeclaredField(name)
            }.getOrNull()

            assertNotNull(
                "UpdateSlotPrefsRequest.$name has no same-named field on TrackedSlotDetail, " +
                    "so toPrefsRequest cannot be carrying it from the slot",
                sourceField
            )

            val expected = sourceField!!.apply { isAccessible = true }.get(slot)
            val actual = field.apply { isAccessible = true }.get(request)

            assertEquals(
                "toPrefsRequest dropped '$name'. Every field left off the request is sent " +
                    "as an explicit null and clears that slot's override -- see issue #261. " +
                    "Add `$name = $name` to toPrefsRequest.",
                expected,
                actual
            )
        }
    }
}
