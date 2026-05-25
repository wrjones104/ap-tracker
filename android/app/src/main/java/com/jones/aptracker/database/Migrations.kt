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


val MIGRATION_7_8 = object : Migration(7, 8) {
    override fun migrate(db: SupportSQLiteDatabase) {

        db.execSQL("""
            CREATE TABLE history_items_new (
                `id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                `roomId` INTEGER,
                `timestamp` TEXT NOT NULL,
                `playerName` TEXT NOT NULL DEFAULT '',
                `itemName` TEXT NOT NULL DEFAULT '',
                `isPlayerFinished` INTEGER NOT NULL DEFAULT 0,
                `itemFlags` INTEGER NOT NULL DEFAULT 0,
                `tracker_id` TEXT,
                `slot_id` INTEGER,
                `icon_name` TEXT,
                `host` TEXT
            )
        """.trimIndent())

        db.execSQL("CREATE INDEX IF NOT EXISTS index_history_items_roomId_playerName_itemName ON history_items_new (roomId, playerName, itemName)")

        db.execSQL("""
            INSERT INTO history_items_new (
                id, roomId, timestamp, tracker_id, slot_id, icon_name, host
            )
            SELECT
                id, roomId, timestamp, tracker_id, slot_id, icon_name, host
            FROM history_items
        """.trimIndent())

        db.execSQL("DROP TABLE history_items")

        db.execSQL("ALTER TABLE history_items_new RENAME TO history_items")
    }
}

val MIGRATION_8_9 = object : Migration(8, 9) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE history_items ADD COLUMN receivingGame TEXT")
        db.execSQL("ALTER TABLE history_items ADD COLUMN senderName TEXT")
        db.execSQL("ALTER TABLE history_items ADD COLUMN senderGame TEXT")
        db.execSQL("ALTER TABLE history_items ADD COLUMN locationName TEXT")
    }
}

val MIGRATION_9_10 = object : Migration(9, 10) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE hints ADD COLUMN itemFlags INTEGER NOT NULL DEFAULT 0")
    }
}

val MIGRATION_10_11 = object : Migration(10, 11) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE hints ADD COLUMN itemOwnerId INTEGER NOT NULL DEFAULT 0")
        db.execSQL("ALTER TABLE hints ADD COLUMN locationOwnerId INTEGER NOT NULL DEFAULT 0")
    }
}
val MIGRATION_11_12 = object : Migration(11, 12) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE history_items ADD COLUMN playerAlias TEXT")
        db.execSQL("ALTER TABLE history_items ADD COLUMN senderAlias TEXT")

        db.execSQL("ALTER TABLE hints ADD COLUMN itemOwnerAlias TEXT")
        db.execSQL("ALTER TABLE hints ADD COLUMN locationOwnerAlias TEXT")
    }
}

val MIGRATION_12_13 = object : Migration(12, 13) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE rooms ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
    }
}

val MIGRATION_13_14 = object : Migration(13, 14) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE rooms ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
    }
}

val MIGRATION_14_15 = object : Migration(14, 15) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE history_items ADD COLUMN receivedCount INTEGER")
    }
}

val MIGRATION_15_16 = object : Migration(15, 16) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("""
            CREATE TABLE IF NOT EXISTS `history_items_new` (
                `id` INTEGER NOT NULL,
                `roomId` INTEGER,
                `timestamp` TEXT NOT NULL,
                `playerName` TEXT NOT NULL,
                `playerAlias` TEXT,
                `receivingGame` TEXT,
                `itemName` TEXT NOT NULL,
                `senderName` TEXT,
                `senderAlias` TEXT,
                `senderGame` TEXT,
                `locationName` TEXT,
                `isPlayerFinished` INTEGER NOT NULL,
                `itemFlags` INTEGER NOT NULL,
                `tracker_id` TEXT,
                `slot_id` INTEGER,
                `icon_name` TEXT,
                `host` TEXT,
                `receivedCount` INTEGER,
                PRIMARY KEY(`id`)
            )
        """.trimIndent())

        db.execSQL("""
            INSERT INTO `history_items_new` (
                `id`, `roomId`, `timestamp`, `playerName`, `playerAlias`, `receivingGame`,
                `itemName`, `senderName`, `senderAlias`, `senderGame`, `locationName`,
                `isPlayerFinished`, `itemFlags`, `tracker_id`, `slot_id`, `icon_name`, `host`, `receivedCount`
            )
            SELECT
                `id`, `roomId`, `timestamp`, `playerName`, `playerAlias`, `receivingGame`,
                `itemName`, `senderName`, `senderAlias`, `senderGame`, `locationName`,
                `isPlayerFinished`, `itemFlags`, `tracker_id`, `slot_id`, `icon_name`, `host`, `receivedCount`
            FROM `history_items`
        """.trimIndent())

        db.execSQL("DROP TABLE `history_items`")

        db.execSQL("ALTER TABLE `history_items_new` RENAME TO `history_items`")

        db.execSQL("CREATE INDEX IF NOT EXISTS `index_history_items_roomId_playerName_itemName` ON `history_items` (`roomId`, `playerName`, `itemName`)")
    }
}