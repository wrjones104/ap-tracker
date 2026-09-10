"""cascade user deletes

Adds ON DELETE CASCADE to every foreign key on the subtree a user owns: the ones
pointing at users.id, the composite key from user_tracked_slots to
user_room_subscriptions, and the grandchildren below both.

The live failure fixed alongside this is an ORM one: milestone_templates had no
collection on User, so deleting a user raised ForeignKeyViolation on
milestone_templates_user_id_fkey. That broke account deletion outright and
rolled back the whole inactive-guest purge batch with it. The relationship in
models.py is what fixes it, because both call sites go through the ORM.

This migration is the database-level backstop for the same class of bug: a bulk
delete, a manual DELETE, or a future table added without its collection. See
#331.

Constraint names are reflected rather than assumed, because these tables were
created across several years of migrations and a couple predate the current
naming. Anything already carrying CASCADE is left alone.

Revision ID: e5d2a7c81f34
Revises: a1c93f70d5e2
Create Date: 2026-09-10 09:00:00.000000

"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5d2a7c81f34'
down_revision: Union[str, Sequence[str], None] = 'a1c93f70d5e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Everything a user owns outright, as (table, local columns, referred table,
# referred columns). A cascade is only worth having if the whole chain has one,
# so the grandchildren are here too: a raw DELETE that reaches milestone_templates
# but stops at milestone_template_items has not deleted anything.
#
# tracked_rooms is deliberately absent. A room is shared by everyone tracking it
# and outlives any one of them, so the room delete path stays ORM-only by design:
# db_run_cleanup in poller.py removes orphaned rooms through the session, and a
# raw DELETE FROM tracked_rooms is meant to be refused.
OWNED_FKS = [
    ('devices', ['user_id'], 'users', ['id']),
    ('user_room_subscriptions', ['user_id'], 'users', ['id']),
    ('user_tracked_slots', ['user_id'], 'users', ['id']),
    ('milestone_templates', ['user_id'], 'users', ['id']),
    ('user_ignore_items', ['user_id'], 'users', ['id']),
    ('user_whitelist_items', ['user_id'], 'users', ['id']),
    (
        'user_tracked_slots',
        ['user_id', 'room_id'],
        'user_room_subscriptions',
        ['user_id', 'room_id'],
    ),
    ('threshold_groups', ['user_tracked_slot_id'], 'user_tracked_slots', ['id']),
    ('threshold_group_items', ['group_id'], 'threshold_groups', ['id']),
    ('milestone_template_items', ['template_id'], 'milestone_templates', ['id']),
    ('cheese_dismissed_trackers', ['user_id'], 'users', ['id']),
]

# Created with CASCADE already, by add_milestone_templates and add_cheese_link_state
# respectively. They are listed above so the list is a complete statement of the
# owned subtree, and so a deployment that somehow lacks the cascade still gets it.
# The upgrade skips them as no-ops; the downgrade leaves them alone rather than
# stripping a cascade it did not add.
PRE_EXISTING_CASCADE = {
    ('milestone_template_items', 'milestone_templates'),
    ('cheese_dismissed_trackers', 'users'),
}


def _matching_fk(inspector, table, local_cols, referred_table):
    """The reflected foreign key on `table` over exactly `local_cols`, or None."""
    for fk in inspector.get_foreign_keys(table):
        if fk.get('referred_table') != referred_table:
            continue
        if list(fk.get('constrained_columns') or []) == local_cols:
            return fk
    return None


def _rewrite(ondelete):
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        # SQLite cannot alter a constraint in place, and no SQLite deployment
        # runs migrations: the test suite builds its schema from models.py,
        # which already carries the cascade.
        logging.info(
            "[MIGRATION] Skipping user foreign key rewrite on %s dialect.",
            bind.dialect.name,
        )
        return

    # Every constraint rewrite takes ACCESS EXCLUSIVE on the referencing table,
    # and alembic/env.py runs the whole upgrade in one transaction, so the locks
    # accumulate and are held until it commits. Three of these tables are ones
    # the poller writes to continuously. Uncontended that is milliseconds; behind
    # an open poller transaction the ALTER waits with no upper bound, and Postgres
    # queues every later reader behind the pending request. The API container is
    # not serving yet at that point, so it would be a silent stall rather than a
    # failed deploy.
    #
    # Fail fast instead. This runs from create_app(), and every container is
    # restart: always, so giving up hands the job to the restart loop, which tries
    # again on a quieter moment. SET LOCAL is scoped to alembic's transaction.
    bind.execute(sa.text("SET LOCAL lock_timeout = '4s'"))

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table, local_cols, referred_table, referred_cols in OWNED_FKS:
        if ondelete is None and (table, referred_table) in PRE_EXISTING_CASCADE:
            continue
        if table not in existing_tables:
            logging.warning("[MIGRATION] Table %s missing; skipping.", table)
            continue

        fk = _matching_fk(inspector, table, local_cols, referred_table)
        if fk is None:
            logging.warning(
                "[MIGRATION] No foreign key on %s.%s -> %s; skipping.",
                table, ','.join(local_cols), referred_table,
            )
            continue

        current = (fk.get('options') or {}).get('ondelete')
        if (current or '').upper() == (ondelete or '').upper():
            continue

        name = fk['name']
        op.drop_constraint(name, table, type_='foreignkey')
        op.create_foreign_key(
            name,
            table,
            referred_table,
            local_cols,
            referred_cols,
            ondelete=ondelete,
        )

    # Handed back so a later migration sharing this transaction does not inherit
    # a timeout it never asked for.
    bind.execute(sa.text("SET LOCAL lock_timeout = DEFAULT"))


def upgrade() -> None:
    _rewrite('CASCADE')


def downgrade() -> None:
    _rewrite(None)
