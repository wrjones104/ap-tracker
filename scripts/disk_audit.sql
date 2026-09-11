-- Read-only disk audit. Safe to run on production.
-- Returns one result set. Expect it to take a minute or two on 10M+ row tables.

WITH live_checksums AS (
    SELECT DISTINCT v.value AS checksum
    FROM tracked_rooms tr,
         LATERAL jsonb_each_text(
             CASE WHEN left(btrim(tr.game_checksums_json), 1) = '{'
                  THEN tr.game_checksums_json::jsonb
                  ELSE '{}'::jsonb
             END
         ) AS v
),
orphan_rooms AS (
    SELECT tr.id, tr.room_id, tr.cached_players_json, tr.cached_cheese_json
    FROM tracked_rooms tr
    LEFT JOIN user_room_subscriptions s ON s.room_id = tr.id
    WHERE s.room_id IS NULL
)

-- 1. Every index on the big tables, with how many times it has been used.
SELECT 1 AS ord,
       'index' AS section,
       relname || '.' || indexrelname AS detail,
       pg_size_pretty(pg_relation_size(indexrelid)) || '   scans: ' || idx_scan AS value,
       pg_relation_size(indexrelid) AS sort_bytes
FROM pg_stat_user_indexes
WHERE relname IN ('notified_items','datapackage_cache','notified_hints',
                  'slot_item_counts','tracked_rooms')

-- 2. Rooms nobody subscribes to, and the cached JSON they are holding.
UNION ALL SELECT 2, 'rooms', 'rooms with no subscribers',
       count(*)::text, 0 FROM orphan_rooms
UNION ALL SELECT 2, 'rooms', 'cached JSON held by those rooms',
       pg_size_pretty(coalesce(sum(pg_column_size(cached_players_json)
                                 + pg_column_size(cached_cheese_json)), 0)),
       0 FROM orphan_rooms

-- 3. notified_items, sliced by what a purge would remove.
UNION ALL SELECT 3, 'notified_items', 'total rows', count(*)::text, 0 FROM notified_items
UNION ALL SELECT 3, 'notified_items', 'older than 90 days',
       count(*)::text, 0 FROM notified_items WHERE timestamp < now() - interval '90 days'
UNION ALL SELECT 3, 'notified_items', 'belong to rooms with no subscribers',
       count(*)::text, 0
FROM notified_items ni
JOIN tracked_rooms tr ON tr.room_id = ni.room_id
LEFT JOIN user_room_subscriptions s ON s.room_id = tr.id
WHERE s.room_id IS NULL
UNION ALL SELECT 3, 'notified_items', 'room row no longer exists at all',
       count(*)::text, 0
FROM notified_items ni
LEFT JOIN tracked_rooms tr ON tr.room_id = ni.room_id
WHERE tr.room_id IS NULL

-- 4. notified_hints.
UNION ALL SELECT 4, 'notified_hints', 'total rows', count(*)::text, 0 FROM notified_hints
UNION ALL SELECT 4, 'notified_hints', 'older than 90 days',
       count(*)::text, 0 FROM notified_hints WHERE timestamp < now() - interval '90 days'

-- 5. datapackage_cache, sliced by whether any live room still references it.
UNION ALL SELECT 5, 'datapackage_cache', 'total rows', count(*)::text, 0 FROM datapackage_cache
UNION ALL SELECT 5, 'datapackage_cache', 'distinct checksums stored',
       count(DISTINCT checksum)::text, 0 FROM datapackage_cache
UNION ALL SELECT 5, 'datapackage_cache', 'checksums referenced by a live room',
       count(*)::text, 0 FROM live_checksums
UNION ALL SELECT 5, 'datapackage_cache', 'rows no live room references',
       count(*)::text, 0
FROM datapackage_cache d
WHERE NOT EXISTS (SELECT 1 FROM live_checksums l WHERE l.checksum = d.checksum)

ORDER BY ord, sort_bytes DESC, detail;
