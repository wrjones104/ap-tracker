// In AppDatabase.kt
package com.jones.aptracker.database

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import com.jones.aptracker.network.HintDao
import com.jones.aptracker.network.HintEntity
import com.jones.aptracker.network.HistoryDao
import com.jones.aptracker.network.HistoryItemEntity
import com.jones.aptracker.network.RoomDao
import com.jones.aptracker.network.RoomEntity

@Database(entities = [RoomEntity::class, HistoryItemEntity::class, HintEntity::class], version = 7) // <-- 1. VERSION UP
abstract class AppDatabase : RoomDatabase() {

    abstract fun roomDao(): RoomDao
    abstract fun historyDao(): HistoryDao
    abstract fun hintDao(): HintDao

    companion object {
        @Volatile
        private var INSTANCE: AppDatabase? = null

        fun getInstance(context: Context): AppDatabase {
            return INSTANCE ?: synchronized(this) {
                val instance = Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "ap_tracker_database"
                )
                    .addMigrations(MIGRATION_5_6, MIGRATION_6_7)
                    .build()
                INSTANCE = instance
                instance
            }
        }
    }
}