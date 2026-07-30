package com.jones.aptracker.database

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface DatapackageDao {
    @Query("SELECT * FROM cached_datapackages WHERE cacheKey = :key OR (roomDbId = :roomDbId AND slotId = :slotId AND roomDbId > 0) OR (game IS NOT NULL AND game != '' AND LOWER(game) = LOWER(:game)) ORDER BY updatedAt DESC LIMIT 1")
    suspend fun getDatapackage(key: String, roomDbId: Int = 0, slotId: Int = 0, game: String? = null): CachedDatapackageEntity?

    @Query("SELECT * FROM cached_datapackages WHERE LOWER(game) = LOWER(:game) ORDER BY updatedAt DESC LIMIT 1")
    suspend fun getDatapackageForGame(game: String): CachedDatapackageEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertDatapackage(datapackage: CachedDatapackageEntity)

    @Query("DELETE FROM cached_datapackages WHERE cacheKey = :key")
    suspend fun deleteDatapackage(key: String)
}
