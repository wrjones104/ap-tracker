package com.jones.aptracker.network

import com.google.gson.annotations.SerializedName

data class WhatsNewResponse(
    val status: String,
    @SerializedName("latest_version") val latestVersion: String? = null,
    val releases: List<ReleaseInfo>? = null
)

data class LatestReleaseResponse(
    val status: String,
    val release: ReleaseInfo? = null
)

data class ReleaseInfo(
    val version: String,
    @SerializedName("release_date") val releaseDate: String? = null,
    val title: String? = null,
    val highlights: List<String>? = null,
    val categories: ReleaseCategories? = null,
    @SerializedName("discord_md") val discordMd: String? = null
)

data class ReleaseCategories(
    val features: List<CategoryItem>? = null,
    val improvements: List<CategoryItem>? = null,
    val fixes: List<CategoryItem>? = null
)

data class CategoryItem(
    val title: String,
    val description: String
)
