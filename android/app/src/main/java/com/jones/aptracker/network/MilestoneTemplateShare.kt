package com.jones.aptracker.network

import android.util.Base64
import com.google.gson.Gson
import com.google.gson.annotations.SerializedName

private const val FORMAT_PREFIX = "APMT1:"
private const val FORMAT_VERSION = 1

// Wire DTOs. Fields are nullable because Gson can populate a Kotlin non-null
// property with null when deserializing untrusted/malformed input, silently
// bypassing the type system — every field here must be validated before use.
//
// Every field carries @SerializedName because these classes are private, so the
// blanket keep rule over this package (which only matches public classes) does not
// cover them. Without the annotation R8 renamed each field to a/b/c and deleted `v`
// outright -- it constant-folded the version from the single construction site,
// not knowing Gson writes the field reflectively. Release builds therefore emitted
// {"a":[{"a":...}]} instead of the documented format, share strings did not survive
// a version bump (R8 naming is not stable across builds), and the format-version
// gate below could never reject anything.
private data class TemplateShareItemDto(
    @SerializedName("item_name") val item_name: String? = null,
    @SerializedName("quantity") val quantity: Int = 0,
    @SerializedName("is_group") val is_group: Boolean = false
)

private data class TemplateShareEntryDto(
    @SerializedName("game") val game: String? = null,
    @SerializedName("name") val name: String? = null,
    @SerializedName("items") val items: List<TemplateShareItemDto>? = null
)

private data class TemplateShareEnvelopeDto(
    @SerializedName("v") val v: Int = 0,
    @SerializedName("templates") val templates: List<TemplateShareEntryDto>? = null
)

// Validated domain model, safe to act on.
data class ParsedTemplateItem(val itemName: String, val quantity: Int, val isGroup: Boolean)
data class ParsedTemplate(val game: String, val name: String, val items: List<ParsedTemplateItem>)

sealed class TemplateImportResult {
    data class Success(val templates: List<ParsedTemplate>) : TemplateImportResult()
    data class Failure(val reason: String) : TemplateImportResult()
}

fun exportMilestoneTemplates(templates: List<MilestoneTemplate>): String {
    val entries = templates.map { template ->
        TemplateShareEntryDto(
            game = template.game_name,
            name = template.name,
            items = template.items.map {
                TemplateShareItemDto(it.item_name, it.quantity, it.is_group)
            }
        )
    }
    val json = Gson().toJson(TemplateShareEnvelopeDto(FORMAT_VERSION, entries))
    val encoded = Base64.encodeToString(json.toByteArray(Charsets.UTF_8), Base64.URL_SAFE or Base64.NO_WRAP)
    return "$FORMAT_PREFIX$encoded"
}

fun parseMilestoneTemplateShareString(input: String): TemplateImportResult {
    val trimmed = input.trim()
    if (trimmed.isEmpty()) {
        return TemplateImportResult.Failure("Paste a template string to import.")
    }

    return try {
        val json = if (trimmed.startsWith(FORMAT_PREFIX)) {
            val encoded = trimmed.removePrefix(FORMAT_PREFIX).replace(Regex("\\s+"), "")
            String(Base64.decode(encoded, Base64.URL_SAFE or Base64.NO_WRAP), Charsets.UTF_8)
        } else {
            // Lenient fallback: accept raw (unencoded) JSON too.
            trimmed
        }

        val envelope = Gson().fromJson(json, TemplateShareEnvelopeDto::class.java)
            ?: return TemplateImportResult.Failure("This doesn't look like a valid template string.")

        if (envelope.v != FORMAT_VERSION) {
            return TemplateImportResult.Failure("Unsupported template format (v${envelope.v}).")
        }

        val rawEntries = envelope.templates
        if (rawEntries.isNullOrEmpty()) {
            return TemplateImportResult.Failure("No templates found in this string.")
        }

        val parsed = rawEntries.map { entry ->
            val game = entry.game?.trim().orEmpty()
            val name = entry.name?.trim().orEmpty()
            val items = (entry.items ?: emptyList()).mapNotNull { itemDto ->
                val itemName = itemDto.item_name?.trim().orEmpty()
                if (itemName.isBlank() || itemDto.quantity < 1) null
                else ParsedTemplateItem(itemName, itemDto.quantity, itemDto.is_group)
            }

            if (game.isBlank() || name.isBlank() || items.isEmpty()) {
                return TemplateImportResult.Failure(
                    "One or more templates are missing a game, name, or valid items."
                )
            }

            ParsedTemplate(game, name, items)
        }

        TemplateImportResult.Success(parsed)
    } catch (e: Exception) {
        TemplateImportResult.Failure("Couldn't read this template string.")
    }
}
