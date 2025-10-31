package com.jones.aptracker.ui

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material.icons.outlined.Build
import androidx.compose.material.icons.outlined.Code
import androidx.compose.material.icons.outlined.Favorite
import androidx.compose.material.icons.outlined.Flag
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.Place
import androidx.compose.material.icons.outlined.SportsEsports
import androidx.compose.material.icons.outlined.Star
import androidx.compose.material.icons.outlined.Token
import androidx.compose.material.icons.outlined.VideogameAsset
import androidx.compose.material.icons.outlined.Report
import androidx.compose.material.icons.outlined.FlutterDash
import androidx.compose.material.icons.outlined.Anchor
import androidx.compose.material.icons.outlined.Thunderstorm
import androidx.compose.material.icons.outlined.PriorityHigh
import androidx.compose.material.icons.outlined.Elderly
import androidx.compose.material.icons.outlined.ThumbUp
import androidx.compose.material.icons.outlined.Landscape
import androidx.compose.ui.graphics.vector.ImageVector

object AppIcons {
    val allIcons = mapOf(
        "default_icon" to Icons.Outlined.Home,
        "star" to Icons.Outlined.Star,
        "videogame" to Icons.Outlined.VideogameAsset,
        "token" to Icons.Outlined.Token,
        "heart" to Icons.Outlined.Favorite,
        "anchor" to Icons.Outlined.Anchor,
        "sports" to Icons.Outlined.SportsEsports,
        "person" to Icons.Outlined.Person,
        "elder" to Icons.Outlined.Elderly,
        "thumb_up" to Icons.Outlined.ThumbUp,
        "landscape" to Icons.Outlined.Landscape,
        "place" to Icons.Outlined.Place,
        "priority" to Icons.Outlined.PriorityHigh,
        "thunderstorm" to Icons.Outlined.Thunderstorm,
        "report" to Icons.Outlined.Report,
        "flag" to Icons.Outlined.Flag,
        "build" to Icons.Outlined.Build,
        "flutterdash" to Icons.Outlined.FlutterDash,
        "code" to Icons.Outlined.Code,
        "bolt" to Icons.Outlined.Bolt
    )
}

fun getIconByName(name: String?): ImageVector {
    return AppIcons.allIcons[name] ?: Icons.Outlined.Home
}