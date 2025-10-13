package com.jones.aptracker.network

import retrofit2.http.GET

// This interface defines the endpoints we will call on our backend
interface ApiService {

    // This function will call the GET /rooms endpoint
    @GET("rooms")
    suspend fun getRooms(): List<Room>
}

// These are "data classes" that tell Retrofit what the JSON looks like.
// It will automatically convert the JSON into these objects.
data class Room(
    val id: Int,
    val room_id: String,
    val alias: String
)