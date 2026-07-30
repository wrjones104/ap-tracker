package com.jones.aptracker.repository

import com.jones.aptracker.network.AddIgnoreItemRequest
import com.jones.aptracker.network.ApiService
import com.jones.aptracker.network.IgnoreItem
import com.jones.aptracker.network.UserProfile

class UserRepository(private val apiService: ApiService) {

    suspend fun getIgnoreList(): List<IgnoreItem> {
        return apiService.getIgnoreList()
    }

    suspend fun addIgnoreItem(itemName: String, gameName: String?, isGroup: Boolean = false): Int {
        val request = AddIgnoreItemRequest(
            itemName = itemName,
            gameName = gameName?.takeIf { it.isNotBlank() },
            isGroup = isGroup
        )
        val response = apiService.addIgnoreItem(request)
        return response.id
    }

    suspend fun updateIgnoreItem(itemId: Int, itemName: String, gameName: String?, isGroup: Boolean = false) {
        val request = AddIgnoreItemRequest(
            itemName = itemName,
            gameName = gameName?.takeIf { it.isNotBlank() },
            isGroup = isGroup
        )
        val response = apiService.updateIgnoreItem(itemId, request)
        if (!response.isSuccessful) {
            throw Exception("Failed to update ignore item: ${response.code()}")
        }
    }

    suspend fun deleteIgnoreItem(itemId: Int) {
        val response = apiService.deleteIgnoreItem(itemId)
        if (!response.isSuccessful) {
            throw Exception("Failed to delete item: ${response.code()}")
        }
    }

    suspend fun getWhitelist(): List<com.jones.aptracker.network.WhitelistItem> {
        return apiService.getWhitelist()
    }

    suspend fun addWhitelistItem(itemName: String, gameName: String?, isGroup: Boolean = false): Int {
        val request = com.jones.aptracker.network.AddWhitelistItemRequest(
            itemName = itemName,
            gameName = gameName?.takeIf { it.isNotBlank() },
            isGroup = isGroup
        )
        val response = apiService.addWhitelistItem(request)
        return response.id
    }

    suspend fun updateWhitelistItem(itemId: Int, itemName: String, gameName: String?, isGroup: Boolean = false) {
        val request = com.jones.aptracker.network.AddWhitelistItemRequest(
            itemName = itemName,
            gameName = gameName?.takeIf { it.isNotBlank() },
            isGroup = isGroup
        )
        val response = apiService.updateWhitelistItem(itemId, request)
        if (!response.isSuccessful) {
            throw Exception("Failed to update whitelist item: ${response.code()}")
        }
    }

    suspend fun deleteWhitelistItem(itemId: Int) {
        val response = apiService.deleteWhitelistItem(itemId)
        if (!response.isSuccessful) {
            throw Exception("Failed to delete whitelist item: ${response.code()}")
        }
    }

    suspend fun getUserProfile(): UserProfile {
        return apiService.getUserProfile()
    }
}