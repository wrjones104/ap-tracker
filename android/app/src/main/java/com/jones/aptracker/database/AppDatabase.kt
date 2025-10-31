package com.jones.aptracker.database

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import com.jones.aptracker.network.* // Ensure HintEntity and HintDao are imported

// --- 1. INCREMENT VERSION TO 6 ---
@Database(entities = [RoomEntity::class, HistoryItemEntity::class, HintEntity::class], version = 6)
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
                    // --- 2. REMOVE destructive migration ---
                    // .fallbackToDestructiveMigration()

                    // --- 3. ADD YOUR NEW MIGRATION ---
                    .addMigrations(MIGRATION_5_6)
                    .build()
                INSTANCE = instance
                instance
            }
        }
    }
}