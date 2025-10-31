package com.jones.aptracker.network

import com.google.gson.annotations.SerializedName

data class DeviceRegisterRequest(
    @SerializedName("fcm_token")
    val fcm_token: String,

    @SerializedName("android_id")
    val android_id: String
)