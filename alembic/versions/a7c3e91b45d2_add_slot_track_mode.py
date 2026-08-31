"""add slot track mode

Adds user_tracked_slots.track_mode, splitting "alert me about this slot" from
"this slot is mine on Cheese Tracker":

  play  -- claimed on Cheese and kept in sync (the historical behavior)
  watch -- alerts only; never pushed to Cheese, never unclaimed by the poller

Also adds users.cheese_last_sync_demoted, the count of slots the most recent
Cheese sync moved from play to watch, so the app can show a post-sync summary.

Every existing row becomes 'play' with a demoted count of 0, so this migration
is behavior-neutral on its own.

Revision ID: a7c3e91b45d2
Revises: b2e75c4a19d8
Create Date: 2026-08-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e91b45d2'
down_revision: Union[str, Sequence[str], None] = 'b2e75c4a19d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('user_tracked_slots', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'track_mode',
            sa.String(length=16),
            nullable=False,
            server_default='play',
        ))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'cheese_last_sync_demoted',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('cheese_last_sync_demoted')

    with op.batch_alter_table('user_tracked_slots', schema=None) as batch_op:
        batch_op.drop_column('track_mode')
