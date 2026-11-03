"""drop the redundant single-column index on datapackage_cache.checksum

ix_datapackage_cache_checksum indexes (checksum). The triple is already indexed
by _checksum_entity_uc on (checksum, entity_type, entity_id), and a btree
answers a lookup on the leading column of a composite key, so the narrow index
is a second copy of information the table already carries.

Figures from production on 2026-11-03, with the retention backlog freshly
drained:

    datapackage_cache    2071 MB heap    2424 MB indexes    13,453,403 rows

Indexes are 58% of this database. Dropping one returns its file to the
operating system at once, unlike a delete, which only returns pages to the
table for reuse -- so this is the one reclaim here that needs no VACUUM FULL,
no pg_repack and no free disk to work in.

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

checksum carries no equivalent load. Its readers are db_get_missing_checksums
(checksum IN (...)) and the eviction sweep's loose index scan (MIN(checksum),
then checksum > previous), which are short btree descents rather than scans.
_checksum_entity_uc serves both for the cost of a wider key, and it had served
674 million scans by 2026-09-11, so it is resident in cache in a way a second
copy of it never needs to be.

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

# An index that leads with checksum and enforces uniqueness: _checksum_entity_uc
# on production, or datapackage_cache_pkey in a schema built from models.py.
# Either one answers every lookup INDEX answers. b7f4e2c9a1d3 explains why the
# two differ.
_COVERING_INDEX_SQL = sa.text("""
    SELECT c.relname
    FROM pg_index i
    JOIN pg_class c ON c.oid = i.indexrelid
    JOIN pg_class t ON t.oid = i.indrelid
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attname = 'checksum'
    WHERE t.relname = 'datapackage_cache'
      AND c.relname <> :dropping
      AND i.indisvalid
      AND (i.indisunique OR i.indisprimary)
      AND i.indkey[0] = a.attnum
    LIMIT 1
""")


def _index_is_valid(bind, name):
    """True only for an index that exists and is usable.

    A CONCURRENTLY build that failed partway leaves the index present but marked
    invalid. Reflection still reports it, so a plain name check would read a
    dead index as a live one.
    """
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_class c "
            "JOIN pg_index i ON i.indexrelid = c.oid "
            "WHERE c.relname = :name AND i.indisvalid"
        ),
        {'name': name},
    ).first()
    return row is not None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        # SQLite builds its schema from models.py, which no longer declares the
        # index. Nothing to migrate.
        logging.info("[MIGRATION] Skipping %s drop on %s dialect.", INDEX, bind.dialect.name)
        return

    if not _index_is_valid(bind, INDEX):
        logging.info("[MIGRATION] %s already absent; nothing to drop.", INDEX)
        return

    covering = bind.execute(_COVERING_INDEX_SQL, {'dropping': INDEX}).scalar()
    if covering is None:
        # Refuse rather than leave checksum lookups to a sequential scan of a
        # 2 GB heap. One of the two covering indexes is always present; if
        # neither is, the schema is not the one this migration was written
        # against and a human should look at it.
        logging.warning(
            "[MIGRATION] No unique index leads with datapackage_cache.checksum; "
            "leaving %s in place.", INDEX
        )
        return

    logging.info("[MIGRATION] %s covers checksum lookups; dropping %s.", covering, INDEX)

    # CONCURRENTLY, which cannot run inside a transaction, so this steps outside
    # the one alembic/env.py wraps around the upgrade.
    #
    # A plain DROP INDEX takes ACCESS EXCLUSIVE on datapackage_cache, and the
    # poller upserts into that table throughout every room setup. Uncontended
    # the drop is a catalog flip, but behind an open poller transaction it waits
    # with no upper bound while Postgres queues every later reader behind the
    # pending request. CONCURRENTLY takes SHARE UPDATE EXCLUSIVE instead and
    # blocks neither readers nor writers, which is worth more here than the
    # lock_timeout escape b7f4e2c9a1d3 used for its in-transaction statements.
    with op.get_context().autocommit_block():
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {INDEX}')

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

    if _index_is_valid(bind, INDEX):
        logging.info("[MIGRATION] %s already present; nothing to rebuild.", INDEX)
        return

    with op.get_context().autocommit_block():
        # Clear the name first: a failed CONCURRENTLY build leaves an invalid
        # index that Postgres never uses but whose name stays taken.
        op.execute(f'DROP INDEX IF EXISTS {INDEX}')
        op.execute(f'CREATE INDEX CONCURRENTLY {INDEX} ON datapackage_cache (checksum)')

    logging.info("[MIGRATION] Rebuilt %s.", INDEX)
