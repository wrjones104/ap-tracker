"""add item index watermark

A dedup floor for received items that survives the retention purge.

The poller decided what was new by comparing the Archipelago feed against
surviving rows in notified_items. That worked only while notified_items was kept
forever. The feed is cumulative and re-enumerated from index zero on every poll,
so once retention deletes a row, the index it held is indistinguishable from one
the slot has never received. It gets re-inserted, re-notified by FCM, and counted
into SlotItemCount again, and the unique constraint does not catch it because the
row it would conflict with is the one retention deleted.

Reproduced against the real _process_received_items, five items with indices 0-4
and 0-2 purged:

    full history    -> added 0  notifications 0
    after 90d purge -> added 3  notifications 3

The count inflation is the worst of it. SlotItemCount is never recomputed
downward (see reconcile_slot_item_counts), so an inflated count stays inflated
and milestone groups fire early and stay fired. On exactly the long-running async
multiworlds the counts exist to serve.

tracked_rooms.item_index_watermark_json holds {slot_id: highest index processed}
and is written in the same transaction as the rows it describes. Nothing derived
from notified_items can serve this purpose, because those are the rows that go
away.

The backfill has to run before retention deletes anything, which it does:
migrations run from create_app() and the janitor runs from the poller loop. A
room purged first would seed a floor from what survived, which is too low.

Revision ID: a3e71c94b8d2
Revises: b4a1c8f5e207
Create Date: 2026-09-11 14:00:00.000000

"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3e71c94b8d2'
down_revision: Union[str, Sequence[str], None] = 'b4a1c8f5e207'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COLUMN = 'item_index_watermark_json'

# One pass over notified_items for the per-slot maximum, folded into one JSON
# object per room, then a single correlated update. Keys are text because JSON
# object keys are; parse_index_watermarks coerces them back to ints.
BACKFILL = """
UPDATE tracked_rooms tr
   SET item_index_watermark_json = w.marks
  FROM (
        SELECT room_id,
               json_object_agg(slot_key, max_idx)::text AS marks
          FROM (
                SELECT room_id,
                       receiving_slot_id::text AS slot_key,
                       MAX(item_index) AS max_idx
                  FROM notified_items
                 WHERE item_index IS NOT NULL
                 GROUP BY room_id, receiving_slot_id
               ) per_slot
         GROUP BY room_id
       ) w
 WHERE tr.room_id = w.room_id
"""


def upgrade() -> None:
    with op.batch_alter_table('tracked_rooms', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            COLUMN, sa.String(), nullable=True, server_default='{}'
        ))

    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        # json_object_agg is Postgres only, and no SQLite deployment runs
        # migrations. A SQLite schema built from models.py starts with '{}',
        # which means "no floor" and falls back to the history set: the
        # pre-retention behaviour, and safe because nothing purges there either.
        logging.info("[MIGRATION] Skipping watermark backfill on %s dialect.", bind.dialect.name)
        return

    # The aggregate reads 10.3 million rows, which does not block writers, but
    # the update that follows takes row locks on tracked_rooms and the poller
    # writes last_successful_poll to those rows every poll. Fail fast and let the
    # restart loop find a quieter moment, as e5d2a7c81f34 does.
    bind.execute(sa.text("SET LOCAL lock_timeout = '4s'"))
    try:
        result = bind.execute(sa.text(BACKFILL))
        logging.info("[MIGRATION] Seeded item index watermarks for %s rooms.", result.rowcount)
    finally:
        # In a finally so an early exit cannot leave the timeout armed for a
        # later migration sharing this transaction.
        bind.execute(sa.text("SET LOCAL lock_timeout = DEFAULT"))


def downgrade() -> None:
    with op.batch_alter_table('tracked_rooms', schema=None) as batch_op:
        batch_op.drop_column(COLUMN)
