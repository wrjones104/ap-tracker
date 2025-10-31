package com.jones.aptracker.ui

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material.icons.outlined.Build
import androidx.compose.material.icons.outlined.Code
import androidx.compose.material.icons.outlined.Flag
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.Place
import androidx.compose.material.icons.outlined.SportsEsports
import androidx.compose.material.icons.outlined.Star
import androidx.compose.material.icons.outlined.VideogameAsset
import androidx.compose.ui.graphics.vector.ImageVector

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

fun getIconByName(name: String?): ImageVector {
    return AppIcons.allIcons[name] ?: Icons.Outlined.Home
}