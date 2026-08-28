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

@Database(
    entities = [
        RoomEntity::class,
        HistoryItemEntity::class,
        HintEntity::class,
        CachedDatapackageEntity::class,
        CachedTrackedSlotEntity::class,
        CachedMilestoneGroupEntity::class,
        CachedGameDatapackageEntity::class
    ],
    version = 25
)
abstract class AppDatabase : RoomDatabase() {

    abstract fun roomDao(): RoomDao
    abstract fun historyDao(): HistoryDao
    abstract fun hintDao(): HintDao
    abstract fun datapackageDao(): DatapackageDao
    abstract fun gameDatapackageDao(): GameDatapackageDao
    abstract fun milestoneCacheDao(): MilestoneCacheDao

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
                    .addMigrations(
                        MIGRATION_5_6, MIGRATION_6_7, MIGRATION_7_8, MIGRATION_8_9,
                        MIGRATION_9_10, MIGRATION_10_11, MIGRATION_11_12, MIGRATION_12_13, MIGRATION_13_14, MIGRATION_14_15,
                        MIGRATION_15_16, MIGRATION_16_17, MIGRATION_17_18, MIGRATION_18_19, MIGRATION_19_20, MIGRATION_20_21,
                        MIGRATION_21_22, MIGRATION_22_23, MIGRATION_23_24, MIGRATION_24_25
                    )
                    .fallbackToDestructiveMigration()
                    .build()
                
                // On first database creation/upgrade to v21, clean all history watermarks in SharedPreferences
                val prefs = context.applicationContext.getSharedPreferences("ap_tracker_sync_watermarks", Context.MODE_PRIVATE)
                if (!prefs.getBoolean("watermarks_cleared_v21", false)) {
                    prefs.edit().clear().putBoolean("watermarks_cleared_v21", true).apply()
                }

                INSTANCE = instance
                instance
            }
        }
    }
}