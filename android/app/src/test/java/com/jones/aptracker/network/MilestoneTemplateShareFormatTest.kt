package com.jones.aptracker.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pins the JSON key names of the `APMT1:` share format.
 *
 * The wire DTOs are private, so the blanket keep rule over this package (public classes
 * only) does not reach them and R8 renamed every field to a/b/c in release builds, while
 * deleting the version field outright. Share strings were therefore neither portable
 * across app versions nor readable by anything but the exact build that wrote them.
 *
 * The fix is `@SerializedName` on every field plus a keep rule for annotated fields, which
 * makes the wire name independent of R8. This test guards the half of that which can be
 * checked on the JVM: that the documented key names are what the parser actually reads. A
 * property renamed without its annotation following fails here.
 *
 * These cases take the lenient raw-JSON path deliberately -- the Base64 branch needs
 * `android.util.Base64`, which is not available to a plain JVM test.
 */
class MilestoneTemplateShareFormatTest {

    private val validJson = """
        {"v":1,"templates":[{"game":"Chrono Trigger","name":"Endgame",
        "items":[{"item_name":"Masamune","quantity":1,"is_group":false},
                 {"item_name":"Elemental Gear","quantity":3,"is_group":true}]}]}
    """.trimIndent()

    @Test
    fun `documented key names parse into the domain model`() {
        val result = parseMilestoneTemplateShareString(validJson)

        assertTrue("expected Success, got $result", result is TemplateImportResult.Success)
        val templates = (result as TemplateImportResult.Success).templates
        assertEquals(1, templates.size)
        assertEquals("Chrono Trigger", templates[0].game)
        assertEquals("Endgame", templates[0].name)
        assertEquals(2, templates[0].items.size)
        assertEquals("Masamune", templates[0].items[0].itemName)
        assertEquals(1, templates[0].items[0].quantity)
        assertEquals(false, templates[0].items[0].isGroup)
        assertEquals("Elemental Gear", templates[0].items[1].itemName)
        assertEquals(3, templates[0].items[1].quantity)
        assertEquals(true, templates[0].items[1].isGroup)
    }

    @Test
    fun `the version field is read, not assumed`() {
        // R8 had constant-folded `v` from the single construction site and deleted the
        // field, so this gate silently accepted anything. It has to be a real read.
        val result = parseMilestoneTemplateShareString(validJson.replace("\"v\":1", "\"v\":2"))

        assertTrue(result is TemplateImportResult.Failure)
        assertTrue(
            "expected the version in the message, got: ${(result as TemplateImportResult.Failure).reason}",
            result.reason.contains("v2")
        )
    }

    @Test
    fun `a renamed key is rejected rather than silently dropped`() {
        val result = parseMilestoneTemplateShareString(validJson.replace("\"item_name\"", "\"itemName\""))

        assertTrue("obfuscated or drifted keys must not parse as valid", result is TemplateImportResult.Failure)
    }
}
