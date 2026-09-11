"""cascade slot_item_counts on room delete

db_run_cleanup in poller.py deletes orphaned rooms and stale guest accounts in
one transaction every 24 hours. It has been failing for as long as
slot_item_counts has existed.

slot_item_counts.room_id references tracked_rooms.room_id with no ON DELETE
clause, so the reference is RESTRICT. TrackedRoom has no ORM relationship to
SlotItemCount either, so SQLAlchemy has no cascade to travel along and emits a
bare DELETE. Postgres refuses it, the except block rolls back, and the stale
guest pruning that shares the transaction is lost with it. Any room that has
ever been polled has rows here, so the failure fires whenever the janitor has
work to do.

The neighbouring migration e5d2a7c81f34 deliberately left tracked_rooms out of
its cascade rewrite, on the reasoning that a room outlives any one user and the
delete path should stay ORM-only. That reasoning holds for the user-owned
subtree it was describing. It does not extend to this table: the ORM path it
was protecting is exactly the one that cannot work here, because the
relationship it would need does not exist.

Production had 1,651 rooms with no subscribers at the time of writing, so this
unblocks real cleanup rather than a hypothetical.

Revision ID: b4a1c8f5e207
Revises: b7f4e2c9a1d3
Create Date: 2026-09-11 12:30:00.000000

"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4a1c8f5e207'
down_revision: Union[str, Sequence[str], None] = 'b7f4e2c9a1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = 'slot_item_counts'
REFERRED = 'tracked_rooms'
LOCAL_COLS = ['room_id']
REFERRED_COLS = ['room_id']


def _matching_fk(inspector):
    """The reflected foreign key on slot_item_counts.room_id, or None.

    Reflected rather than assumed: the constraint was created by alembic
    autogenerate without an explicit name, so its name is whatever Postgres
    defaulted to.
    """
    for fk in inspector.get_foreign_keys(TABLE):
        if fk.get('referred_table') != REFERRED:
            continue
        if list(fk.get('constrained_columns') or []) == LOCAL_COLS:
            return fk
    return None


def _rewrite(ondelete):
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        # SQLite cannot alter a constraint in place, and no SQLite deployment
        # runs migrations: the test suite builds its schema from models.py,
        # which already carries the cascade.
        logging.info(
            "[MIGRATION] Skipping slot_item_counts foreign key rewrite on %s dialect.",
            bind.dialect.name,
        )
        return

    # Same fail-fast reasoning as e5d2a7c81f34: the constraint rewrite takes
    # ACCESS EXCLUSIVE on a table the poller writes continuously, and waiting
    # behind an open poller transaction would queue every later reader. Giving
    # up hands the job to the restart loop and a quieter moment.
    bind.execute(sa.text("SET LOCAL lock_timeout = '4s'"))

    # try/finally because every skip below is an early return, and the handback
    # at the end is not optional: a later migration sharing this transaction
    # would otherwise inherit a 4 second timeout it never asked for, which is
    # precisely the leak this handback exists to prevent.
    try:
        inspector = sa.inspect(bind)
        if TABLE not in set(inspector.get_table_names()):
            logging.warning("[MIGRATION] Table %s missing; skipping.", TABLE)
            return

        fk = _matching_fk(inspector)
        if fk is None:
            logging.warning(
                "[MIGRATION] No foreign key on %s.%s -> %s; skipping.",
                TABLE, ','.join(LOCAL_COLS), REFERRED,
            )
            return

        current = (fk.get('options') or {}).get('ondelete')
        if (current or '').upper() == (ondelete or '').upper():
            logging.info("[MIGRATION] %s already has the requested ON DELETE; skipping.", TABLE)
            return

        name = fk['name']
        op.drop_constraint(name, TABLE, type_='foreignkey')
        op.create_foreign_key(name, TABLE, REFERRED, LOCAL_COLS, REFERRED_COLS, ondelete=ondelete)
        logging.info("[MIGRATION] Rewrote %s.%s ON DELETE %s.", TABLE, name, ondelete or 'NO ACTION')
    finally:
        bind.execute(sa.text("SET LOCAL lock_timeout = DEFAULT"))


def upgrade() -> None:
    _rewrite('CASCADE')


def downgrade() -> None:
    _rewrite(None)
