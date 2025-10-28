package com.jones.aptracker.database

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import com.jones.aptracker.network.* // Ensure HintEntity and HintDao are imported

// --- INCREMENT VERSION TO 5 ---
@Database(entities = [RoomEntity::class, HistoryItemEntity::class, HintEntity::class], version = 5)
abstract class AppDatabase : RoomDatabase() {

    abstract fun roomDao(): RoomDao
    abstract fun historyDao(): HistoryDao
    abstract fun hintDao(): HintDao // --- ADD HINT DAO ---

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
                    // Since we incremented the version and didn't provide a migration,
                    // this will delete and recreate the DB. Fine for dev.
                    .fallbackToDestructiveMigration()
                    .build()
                INSTANCE = instance
                instance
            }
        }
    }
}