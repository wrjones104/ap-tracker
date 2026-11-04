"""drop the redundant single-column index on datapackage_cache.checksum

ix_datapackage_cache_checksum indexes (checksum). The triple is already indexed
by _checksum_entity_uc on (checksum, entity_type, entity_id), and a btree
answers a lookup on the leading column or columns of a composite key, so the
narrow index is a second copy of information the table already carries.

Figures from production on 2026-11-03, with the retention backlog freshly
drained:

    datapackage_cache    2071 MB heap    2424 MB indexes    13,453,403 rows

Indexes are 58% of this database. Dropping one returns its file to the
operating system at once, unlike a delete, which only returns pages to the
table for reuse -- so this is the one reclaim here that needs no VACUUM FULL,
no pg_repack and no free disk to work in.

Every reader of this column filters on checksum first, and most of them filter
on entity_type straight after, which uses two leading columns of
_checksum_entity_uc rather than one:

    routes/game_routes.py       checksum == x AND entity_type IN (...)
                                (item groups, items, locations, the bundle)
    routes/rooms_routes.py      checksum IN (...)
    poller.py                   checksum IN (...) AND entity_id IN (...)
    services/retention_service  checksum IN (...), and the eviction sweep's
                                loose index scan: MIN(checksum), then
                                checksum > previous

None of those is a scan of the narrow index; they are btree descents that the
composite serves for the cost of a wider key. _checksum_entity_uc had served
674 million scans by 2026-09-11, so it is resident in cache in a way a second
copy of it never needs to be. The one query on this table that does not lead
with checksum, game_routes.py's game -> checksum lookup, reads
ix_datapackage_cache_game, which stays.

Only this index is dropped, although ix_notified_items_room_id and
ix_notified_hints_room_id are redundant in exactly the same structural sense.
Those two are load-bearing. purge_orphaned_room_events in
services/retention_service.py reads SELECT DISTINCT room_id from both tables on
every janitor run, which is an index-only scan of the narrow btree and the
reason that function stopped re-scanning a 977 MB heap per batch;
ix_notified_items_room_id had served 22 million lifetime scans by the time
b7f4e2c9a1d3 was written. Moving those reads onto a three- and a five-column
index roughly doubles the pages they touch, to save a few hundred megabytes.
Not worth it. See #534.

Revision ID: c7a2e5b48f16
Revises: e4b9c2d7f8a1
Create Date: 2026-11-03 17:30:00.000000

"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7a2e5b48f16'
down_revision: Union[str, Sequence[str], None] = 'e4b9c2d7f8a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX = 'ix_datapackage_cache_checksum'

# How long either direction waits on the transactions a CONCURRENTLY statement
# has to outlast before it gives up. This migration runs from create_app() while
# holding the migration advisory lock, so an unbounded wait here is a boot that
# never finishes, for the poller as well as the api: one session left idle in
# transaction on datapackage_cache would be enough. Giving up instead hands the
# job to the restart loop and a quieter moment, which is how b7f4e2c9a1d3 treats
# the same risk. lock_timeout covers these waits because they are taken as locks
# on the lockers' virtual transaction ids.
LOCK_TIMEOUT = '30s'

# An index that can answer every lookup INDEX answers: unique, not partial,
# btree (so MIN(checksum) and checksum > previous stay ordered scans), and
# leading with checksum. On production that is _checksum_entity_uc; in a schema
# built from models.py it is datapackage_cache_pkey. b7f4e2c9a1d3 explains why
# the two differ.
_COVERING_INDEX_SQL = sa.text("""
    SELECT c.relname
    FROM pg_index i
    JOIN pg_class c ON c.oid = i.indexrelid
    JOIN pg_am am ON am.oid = c.relam AND am.amname = 'btree'
    JOIN pg_attribute a ON a.attrelid = i.indrelid
                       AND a.attname = 'checksum'
                       AND NOT a.attisdropped
    WHERE i.indrelid = to_regclass('datapackage_cache')
      AND c.relname <> :dropping
      AND i.indisvalid
      AND i.indpred IS NULL
      AND (i.indisunique OR i.indisprimary)
      AND i.indkey[0] = a.attnum
    LIMIT 1
""")


def _index_state(bind, name):
    """None if absent, True if valid, False if present but invalid.

    The three cases are not interchangeable here, and conflating two of them is
    how this migration first shipped. DROP INDEX CONCURRENTLY runs in phases
    that commit separately: the first clears indisvalid, and only the last
    unlinks the file. An interrupted drop -- a cancelled statement, a container
    killed mid-deploy -- therefore leaves the index present, invalid, holding
    all of its disk, and still maintained by writes until the phase that marks
    it dead. Alembic has not stamped the revision at that point, so the retry
    comes back here: reading that as "already gone" would stamp the revision
    over an index nothing will ever clean up.

    b7f4e2c9a1d3 only needed valid-or-not because it was guarding a build, where
    an invalid index is work to redo rather than work half done.
    """
    row = bind.execute(
        sa.text(
            "SELECT i.indisvalid FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE i.indrelid = to_regclass('datapackage_cache') "
            "AND c.relname = :name"
        ),
        {'name': name},
    ).first()
    return None if row is None else bool(row[0])


def _drop_concurrently(name):
    """DROP INDEX CONCURRENTLY, outside the transaction and under a timeout.

    CONCURRENTLY cannot run inside a transaction, so this steps outside the one
    alembic/env.py wraps around the migration. It is worth the awkwardness: a
    plain DROP INDEX takes ACCESS EXCLUSIVE on datapackage_cache, which the
    poller upserts into throughout every room setup, and Postgres queues every
    later reader behind that pending request. CONCURRENTLY takes SHARE UPDATE
    EXCLUSIVE and blocks neither readers nor writers.

    SET, not SET LOCAL: there is no transaction here for LOCAL to scope to.
    """
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '%s'" % LOCK_TIMEOUT)
        try:
            op.execute('DROP INDEX CONCURRENTLY IF EXISTS %s' % name)
        finally:
            op.execute('RESET lock_timeout')


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        # SQLite builds its schema from models.py, which no longer declares the
        # index. Nothing to migrate.
        logging.info("[MIGRATION] Skipping %s drop on %s dialect.", INDEX, bind.dialect.name)
        return

    state = _index_state(bind, INDEX)
    if state is None:
        logging.info("[MIGRATION] %s already absent; nothing to drop.", INDEX)
        return

    if state:
        covering = bind.execute(_COVERING_INDEX_SQL, {'dropping': INDEX}).scalar()
        if covering is None:
            # Refuse rather than leave checksum lookups to a sequential scan of
            # a 2 GB heap. One of the two covering indexes is always present; if
            # neither is, the schema is not the one this migration was written
            # against and a human should look at it.
            logging.warning(
                "[MIGRATION] No unique index leads with datapackage_cache.checksum; "
                "leaving %s in place.", INDEX
            )
            return
        logging.info("[MIGRATION] %s covers checksum lookups; dropping %s.", covering, INDEX)
    else:
        # No covering check in this branch: an invalid index answers nothing
        # already, so finishing its drop cannot take an index away from the
        # planner, and refusing would strand the file instead.
        logging.info("[MIGRATION] %s is present but invalid; finishing its drop.", INDEX)

    _drop_concurrently(INDEX)
    logging.info("[MIGRATION] Dropped %s.", INDEX)


def downgrade() -> None:
    """Rebuild the index.

    More expensive than the upgrade: this one reads all 13.45 million rows,
    where dropping it only unlinked a file.
    """
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        logging.info(
            "[MIGRATION] Skipping %s rebuild on %s dialect.", INDEX, bind.dialect.name
        )
        return

    state = _index_state(bind, INDEX)
    if state:
        logging.info("[MIGRATION] %s already present; nothing to rebuild.", INDEX)
        return

    if state is False:
        # The name is taken by an invalid index from a build or drop that failed
        # partway. Clear it CONCURRENTLY: a plain DROP INDEX here would take the
        # ACCESS EXCLUSIVE lock the rest of this migration goes out of its way
        # to avoid.
        _drop_concurrently(INDEX)

    with op.get_context().autocommit_block():
        # No timeout on the build. Waiting out the open transactions is how
        # CONCURRENTLY produces a valid index; giving up would leave an invalid
        # one, which is the state this function exists to get out of.
        op.execute('CREATE INDEX CONCURRENTLY %s ON datapackage_cache (checksum)' % INDEX)

    logging.info("[MIGRATION] Rebuilt %s.", INDEX)
