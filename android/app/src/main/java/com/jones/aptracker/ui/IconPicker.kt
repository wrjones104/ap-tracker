package com.jones.aptracker.ui

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.ui.graphics.vector.ImageVector

// 1. Define the list of available icons
object AppIcons {
    val allIcons = mapOf(
        "default_icon" to Icons.Outlined.Home,
        "star" to Icons.Outlined.Star,
        "videogame" to Icons.Outlined.VideogameAsset,
        "sports" to Icons.Outlined.SportsEsports,
        "person" to Icons.Outlined.Person,
        "place" to Icons.Outlined.Place,
        "flag" to Icons.Outlined.Flag,
        "build" to Icons.Outlined.Build,
        "code" to Icons.Outlined.Code,
        "bolt" to Icons.Outlined.Bolt
    )
}

// 2. Helper function to get an icon by its name
fun getIconByName(name: String?): ImageVector {
    return AppIcons.allIcons[name] ?: Icons.Outlined.Home // Return Home icon as a fallback
}