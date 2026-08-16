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

val MIGRATION_16_17 = object : Migration(16, 17) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("DELETE FROM history_items")
        db.execSQL("DELETE FROM hints")
    }
}

val MIGRATION_17_18 = object : Migration(17, 18) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE rooms ADD COLUMN is_suspended INTEGER NOT NULL DEFAULT 0")
        db.execSQL("ALTER TABLE rooms ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        db.execSQL("ALTER TABLE rooms ADD COLUMN web_url TEXT")
    }
}

val MIGRATION_18_19 = object : Migration(18, 19) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("""
            CREATE TABLE IF NOT EXISTS `cached_datapackages` (
                `cacheKey` TEXT NOT NULL,
                `game` TEXT,
                `roomDbId` INTEGER,
                `slotId` INTEGER,
                `itemsJson` TEXT NOT NULL,
                `locationsJson` TEXT NOT NULL,
                `updatedAt` INTEGER NOT NULL,
                PRIMARY KEY(`cacheKey`)
            )
        """.trimIndent())
    }
}

val MIGRATION_19_20 = object : Migration(19, 20) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("DROP TABLE IF EXISTS `cached_datapackages`")
        db.execSQL("""
            CREATE TABLE IF NOT EXISTS `cached_datapackages` (
                `cacheKey` TEXT NOT NULL,
                `game` TEXT,
                `roomDbId` INTEGER,
                `slotId` INTEGER,
                `itemsJson` TEXT NOT NULL,
                `locationsJson` TEXT NOT NULL,
                `updatedAt` INTEGER NOT NULL,
                PRIMARY KEY(`cacheKey`)
            )
        """.trimIndent())
    }
}

val MIGRATION_20_21 = object : Migration(20, 21) {
    override fun migrate(db: SupportSQLiteDatabase) {
        // Schema structure is unchanged; migration triggers reset of SharedPreferences watermarks for sequence sync
    }
}

/**
 * Adds server-computed isIgnored/isWhitelisted flags to history_items and hints.
 * These used to be derived entirely on-device by matching item names against the
 * ignore/whitelist lists, which couldn't resolve item-group rules (group membership
 * isn't known to the client). The server now evaluates this using the same logic
 * as notification filtering and sends the result down directly.
 *
 * Existing locally-cached rows default to false until they're next re-synced from
 * the server; this only affects the ignore/whitelist display state of already-synced
 * history, not new items.
 */
val MIGRATION_21_22 = object : Migration(21, 22) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE history_items ADD COLUMN isIgnored INTEGER NOT NULL DEFAULT 0")
        db.execSQL("ALTER TABLE history_items ADD COLUMN isWhitelisted INTEGER NOT NULL DEFAULT 0")
        db.execSQL("ALTER TABLE hints ADD COLUMN isIgnored INTEGER NOT NULL DEFAULT 0")
        db.execSQL("ALTER TABLE hints ADD COLUMN isWhitelisted INTEGER NOT NULL DEFAULT 0")
    }
}

/**
 * Adds the local milestone cache backing the Milestones home screen widget.
 *
 * The widget previously called the network from inside its Glance composition -- a ~750 KB
 * tracked-slots fetch plus one threshold-groups request per slot, sequentially -- which left it
 * showing its "Setup needed" placeholder for seconds after configuration. The sync layer now
 * writes these two tables and the widget reads only from them.
 *
 * Both tables are pure caches: they are rebuilt on the next sync, so there is nothing to backfill.
 */
val MIGRATION_22_23 = object : Migration(22, 23) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("""
            CREATE TABLE IF NOT EXISTS `cached_tracked_slots` (
                `roomDbId` INTEGER NOT NULL,
                `slotId` INTEGER NOT NULL,
                `roomAlias` TEXT NOT NULL,
                `playerName` TEXT NOT NULL,
                `playerAlias` TEXT,
                `isArchived` INTEGER NOT NULL,
                `updatedAt` INTEGER NOT NULL,
                PRIMARY KEY(`roomDbId`, `slotId`)
            )
        """.trimIndent())

        db.execSQL("""
            CREATE TABLE IF NOT EXISTS `cached_milestone_groups` (
                `roomDbId` INTEGER NOT NULL,
                `slotId` INTEGER NOT NULL,
                `groupId` INTEGER NOT NULL,
                `name` TEXT,
                `isTriggered` INTEGER NOT NULL,
                `itemsJson` TEXT NOT NULL,
                `updatedAt` INTEGER NOT NULL,
                PRIMARY KEY(`roomDbId`, `slotId`, `groupId`)
            )
        """.trimIndent())
    }
}
