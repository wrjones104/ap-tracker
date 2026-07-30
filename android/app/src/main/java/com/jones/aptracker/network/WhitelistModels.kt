package com.jones.aptracker.network

import com.google.gson.annotations.SerializedName

data class WhitelistItem(
    val id: Int,
    @SerializedName("item_name") val itemName: String,
    @SerializedName("game_name") val gameName: String?,
    @SerializedName("is_group") val isGroup: Boolean = false,
    @SerializedName("created_at") val createdAt: String
)

data class AddWhitelistItemRequest(
    @SerializedName("item_name") val itemName: String,
    @SerializedName("game_name") val gameName: String? = null,
    @SerializedName("is_group") val isGroup: Boolean = false
)

data class AddWhitelistItemResponse(
    val message: String,
    val id: Int
)
