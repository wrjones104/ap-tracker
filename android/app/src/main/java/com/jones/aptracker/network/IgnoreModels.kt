package com.jones.aptracker.network

data class IgnoreItem(
    val id: Int,
    @com.google.gson.annotations.SerializedName("item_name") val itemName: String,
    @com.google.gson.annotations.SerializedName("game_name") val gameName: String?,
    @com.google.gson.annotations.SerializedName("is_group") val isGroup: Boolean = false,
    @com.google.gson.annotations.SerializedName("created_at") val createdAt: String
)

data class AddIgnoreItemRequest(
    @com.google.gson.annotations.SerializedName("item_name") val itemName: String,
    @com.google.gson.annotations.SerializedName("game_name") val gameName: String? = null,
    @com.google.gson.annotations.SerializedName("is_group") val isGroup: Boolean = false
)

data class AddIgnoreItemResponse(
    val message: String,
    val id: Int
)