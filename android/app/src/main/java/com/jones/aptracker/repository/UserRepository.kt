package com.jones.aptracker.repository

import com.jones.aptracker.network.AddIgnoreItemRequest
import com.jones.aptracker.network.ApiService
import com.jones.aptracker.network.IgnoreItem

class UserRepository(private val apiService: ApiService) {

    suspend fun getIgnoreList(): List<IgnoreItem> {
        return apiService.getIgnoreList()
    }

    suspend fun addIgnoreItem(itemName: String, gameName: String?): Int {
        val request = AddIgnoreItemRequest(
            item_name = itemName,
            game_name = gameName?.takeIf { it.isNotBlank() }
        )
        val response = apiService.addIgnoreItem(request)
        return response.id
    }

    suspend fun deleteIgnoreItem(itemId: Int) {
        val response = apiService.deleteIgnoreItem(itemId)
        if (!response.isSuccessful) {
            throw Exception("Failed to delete item: ${response.code()}")
        }
    }
}