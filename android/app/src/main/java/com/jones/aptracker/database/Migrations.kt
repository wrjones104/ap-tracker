package com.jones.aptracker.database

import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/**
 * Migration from database version 5 to 6.
 *
 * This migration fixes the 'hints' table. The original schema (v5)
 * incorrectly used a local, auto-incrementing 'local_id' as the
 * primary key. This caused data duplication.
 *
 * This migration creates a new table with the correct schema
 * (using 'hint_db_id' as the primary key), copies the data,
 * drops the old table, and renames the new one.
 *
 * **It also de-duplicates the data** using GROUP BY to prevent
 * crashes from primary key conflicts.
 */
val MIGRATION_5_6 = object : Migration(5, 6) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("""
            CREATE TABLE hints_new (
                `hint_db_id` INTEGER NOT NULL,
                `roomDbId` INTEGER NOT NULL,
                `roomAlias` TEXT NOT NULL,
                `hintType` TEXT NOT NULL,
                `itemOwnerName` TEXT NOT NULL,
                `locationOwnerName` TEXT NOT NULL,
                `itemName` TEXT NOT NULL,
                `locationName` TEXT NOT NULL, 
                `isFound` INTEGER NOT NULL,
                `timestamp` TEXT NOT NULL,
                PRIMARY KEY(`hint_db_id`)
            )
        """.trimIndent())

        db.execSQL("""
            INSERT INTO hints_new (
                hint_db_id, roomDbId, roomAlias, hintType, itemOwnerName, 
                locationOwnerName, itemName, locationName, isFound, timestamp
            )
            SELECT 
                hint_db_id, roomDbId, roomAlias, hintType, itemOwnerName, 
                locationOwnerName, itemName, locationName, isFound, timestamp
            FROM hints
            GROUP BY hint_db_id
        """.trimIndent())

        db.execSQL("DROP TABLE hints")

        db.execSQL("ALTER TABLE hints_new RENAME TO hints")
    }
}

val MIGRATION_6_7 = object : Migration(6, 7) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE history_items ADD COLUMN host TEXT")
    }
}