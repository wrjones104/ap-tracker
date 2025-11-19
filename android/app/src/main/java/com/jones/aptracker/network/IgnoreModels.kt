package com.jones.aptracker.network

data class IgnoreItem(
    val id: Int,
    val item_name: String,
    val game_name: String?,
    val created_at: String
)

data class AddIgnoreItemRequest(
    val item_name: String,
    val game_name: String? = null
)

data class AddIgnoreItemResponse(
    val message: String,
    val id: Int
)