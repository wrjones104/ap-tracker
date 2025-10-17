// In: app/src/main/java/com/jones/aptracker/database/AppDatabase.kt

package com.jones.aptracker.database

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import com.jones.aptracker.network.HistoryDao
import com.jones.aptracker.network.HistoryItemEntity
import com.jones.aptracker.network.RoomDao
import com.jones.aptracker.network.RoomEntity

@Database(entities = [RoomEntity::class, HistoryItemEntity::class], version = 3)
abstract class AppDatabase : RoomDatabase() {

    abstract fun roomDao(): RoomDao
    abstract fun historyDao(): HistoryDao

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
                    // This is a simple destructive migration. For a real app,
                    // you would write a proper migration plan.
                    .fallbackToDestructiveMigration()
                    .build()
                INSTANCE = instance
                instance
            }
        }
    }
}