"""reclaim unused index space

Two indexes were costing 367 MB in production while answering almost nothing.
Figures are from pg_stat_user_indexes on 2026-09-11, lifetime scan counts:

    datapackage_cache_pkey        268 MB        2 scans
    ix_notifieditem_item_index     99 MB      141 scans

For contrast, _checksum_entity_uc on the same table had served 674 million
scans, and ix_notified_items_room_id 22 million.

datapackage_cache.id was a surrogate key nothing read. No foreign key pointed at
it, no query ordered or filtered by it, and the upsert in
services/datapackage_service.py conflicts on (checksum, entity_type, entity_id)
instead. Dropping the column drops its primary key index with it.

The table is deliberately left with no primary key constraint afterwards.
_checksum_entity_uc already enforces exactly the identity the model declares, and
the obvious tidy-up of promoting it with ADD PRIMARY KEY USING INDEX is not
available: that index is owned by a unique constraint, and Postgres refuses to
reuse an index that already backs one. The only alternative would be building a
second copy of a 1.5 GB index to hold a constraint that changes no behaviour.
REPLICA IDENTITY is pointed at the unique index instead, so row identity for
replication survives the loss of the primary key.

ix_notifieditem_item_index existed for the legacy backfill probes, and both of
them ask only for rows where item_index IS NULL: db_has_unindexed_items at
poller.py, and the per-room legacy purge. A partial index over just those rows
answers the same questions for a few kilobytes.

Space: dropping an index returns its space immediately. DROP COLUMN is
catalog-only in Postgres, so the heap bytes behind the old id column are not
returned until the table is next rewritten. Expect the pkey's 268 MB back on
deploy and roughly 90 MB more at the next repack.

Revision ID: b7f4e2c9a1d3
Revises: e5d2a7c81f34
Create Date: 2026-09-11 12:00:00.000000

"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f4e2c9a1d3'
down_revision: Union[str, Sequence[str], None] = 'e5d2a7c81f34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PARTIAL_INDEX = 'ix_notifieditem_unindexed'
OLD_INDEX = 'ix_notifieditem_item_index'
NATURAL_KEY = '_checksum_entity_uc'


def _index_is_valid(bind, name):
    """True only for an index that exists and is usable.

    A CREATE INDEX CONCURRENTLY that fails partway leaves the index present but
    marked invalid. Reflection still reports it, so a plain name check would
    decide the work was already done and leave a dead index in place forever.
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
        # SQLite builds its schema from models.py, which already carries both
        # changes. Nothing to migrate.
        logging.info("[MIGRATION] Skipping index reclamation on %s dialect.", bind.dialect.name)
        return

    # Fail fast rather than queueing readers behind us. Both statements below
    # take ACCESS EXCLUSIVE on tables the poller reads and writes continuously.
    # Uncontended that is milliseconds; behind an open poller transaction it
    # waits with no upper bound, and Postgres queues every later reader behind
    # the pending request. Same reasoning as e5d2a7c81f34: this runs from
    # create_app() and every container is restart: always, so giving up hands the
    # job to the restart loop and a quieter moment.
    bind.execute(sa.text("SET LOCAL lock_timeout = '4s'"))

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # --- 1. datapackage_cache: drop the surrogate key -------------------------
    if 'datapackage_cache' in tables:
        columns = {c['name'] for c in inspector.get_columns('datapackage_cache')}
        uniques = {u['name'] for u in inspector.get_unique_constraints('datapackage_cache')}

        if 'id' in columns:
            # Point replica identity at the natural key before the primary key
            # goes away. Without this the table would fall back to REPLICA
            # IDENTITY NOTHING once it has no primary key, which breaks logical
            # replication of updates and deletes. Catalog-only, no rewrite.
            if NATURAL_KEY in uniques:
                op.execute(
                    f'ALTER TABLE datapackage_cache REPLICA IDENTITY USING INDEX {NATURAL_KEY}'
                )
            else:
                logging.warning(
                    "[MIGRATION] %s absent; leaving replica identity alone.", NATURAL_KEY
                )

            # Drops datapackage_cache_pkey along with the column.
            op.drop_column('datapackage_cache', 'id')
            logging.info("[MIGRATION] Dropped datapackage_cache.id and its primary key index.")
        else:
            logging.info("[MIGRATION] datapackage_cache.id already absent; skipping.")

    # --- 2. notified_items: full btree -> partial ------------------------------
    if 'notified_items' in tables:
        # Built CONCURRENTLY, which cannot run inside a transaction, so this
        # steps outside the one alembic/env.py wraps around the whole upgrade.
        #
        # Worth the awkwardness. A plain CREATE INDEX here scans 10.3 million
        # rows while holding a lock that blocks every write to notified_items,
        # and the poller writes to it continuously. lock_timeout does not help:
        # it bounds how long we wait to acquire a lock, not how long we hold
        # one. CONCURRENTLY pays for a second scan and blocks no writers.
        if not _index_is_valid(bind, PARTIAL_INDEX):
            with op.get_context().autocommit_block():
                # A CONCURRENTLY build that failed leaves an invalid index
                # behind. Postgres never uses it but the name stays taken, so
                # clear it rather than skipping the rebuild forever.
                op.execute(f'DROP INDEX IF EXISTS {PARTIAL_INDEX}')
                op.execute(
                    f'CREATE INDEX CONCURRENTLY {PARTIAL_INDEX} '
                    f'ON notified_items (room_id) WHERE item_index IS NULL'
                )
            logging.info("[MIGRATION] Created partial index %s.", PARTIAL_INDEX)

        # autocommit_block ended the transaction that carried the SET LOCAL, so
        # the timeout has to be re-armed for the drop below.
        bind.execute(sa.text("SET LOCAL lock_timeout = '4s'"))

        if OLD_INDEX in {i['name'] for i in sa.inspect(bind).get_indexes('notified_items')}:
            # Catalog-only once the lock is held, unlike the build above.
            op.drop_index(OLD_INDEX, table_name='notified_items')
            logging.info("[MIGRATION] Dropped %s.", OLD_INDEX)

    # Handed back so a later migration sharing this transaction does not inherit
    # a timeout it never asked for.
    bind.execute(sa.text("SET LOCAL lock_timeout = DEFAULT"))


def downgrade() -> None:
    """Restore both indexes.

    Recreating datapackage_cache.id rewrites the whole table, because every row
    needs the new column materialised and the sequence walked. On a table of this
    size that is a long ACCESS EXCLUSIVE lock, not a catalog flip. The upgrade is
    cheap and the downgrade is not.
    """
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        logging.info("[MIGRATION] Skipping index reclamation rollback on %s dialect.", bind.dialect.name)
        return

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'notified_items' in tables:
        indexes = {i['name'] for i in inspector.get_indexes('notified_items')}
        if not _index_is_valid(bind, OLD_INDEX):
            # CONCURRENTLY for the same reason as the upgrade: this one indexes
            # every row rather than the handful with a null item_index, so it is
            # the more expensive of the two builds, not the cheaper.
            with op.get_context().autocommit_block():
                op.execute(f'DROP INDEX IF EXISTS {OLD_INDEX}')
                op.execute(
                    f'CREATE INDEX CONCURRENTLY {OLD_INDEX} ON notified_items (item_index)'
                )
        if PARTIAL_INDEX in indexes:
            op.drop_index(PARTIAL_INDEX, table_name='notified_items')

    if 'datapackage_cache' in tables:
        columns = {c['name'] for c in inspector.get_columns('datapackage_cache')}
        if 'id' not in columns:
            # SERIAL creates the owning sequence and populates every existing row
            # as part of the rewrite, which plain add_column cannot do for a NOT
            # NULL column with no default.
            op.execute('ALTER TABLE datapackage_cache ADD COLUMN id SERIAL')
            op.execute('ALTER TABLE datapackage_cache ADD PRIMARY KEY (id)')
            op.execute('ALTER TABLE datapackage_cache REPLICA IDENTITY DEFAULT')
