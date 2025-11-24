package com.jones.aptracker.ui

fun getDisplayName(originalName: String?, alias: String?, useCondensed: Boolean): String {
    val safeOriginal = originalName ?: "Unknown"
    if (alias.isNullOrBlank()) return safeOriginal

    return if (useCondensed) {
        alias
    } else {
        "$alias ($safeOriginal)"
    }
}