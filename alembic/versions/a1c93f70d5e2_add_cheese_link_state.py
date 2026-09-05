"""add cheese link state

Makes the app the owner of a user's room library, and Cheese Tracker a place a
room can optionally be mirrored to. See #323.

  user_room_subscriptions.cheese_link        -- 'none' | 'linked'
  user_room_subscriptions.cheese_unlisted_at -- linked room missing from the dashboard
  users.cheese_publish_new_rooms             -- default for the add-room checkbox
  cheese_dismissed_trackers                  -- suggestions the user said no to

The backfill preserves what every existing user already has: a subscription
whose room carries a cheese_tracker_id is marked 'linked', everything else
'none'. Nothing changes state as a result of this migration; what changes is
that the sync can no longer delete a subscription, so the column decides what
gets pushed rather than deciding what survives.

Revision ID: a1c93f70d5e2
Revises: d7b41e9c2a55
Create Date: 2026-09-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c93f70d5e2'
down_revision: Union[str, Sequence[str], None] = 'd7b41e9c2a55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('user_room_subscriptions', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'cheese_link',
            sa.String(length=16),
            nullable=False,
            server_default='none',
        ))
        batch_op.add_column(sa.Column('cheese_unlisted_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'cheese_publish_new_rooms',
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ))
        batch_op.add_column(sa.Column(
            'cheese_last_sync_unlisted',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ))

    op.create_table(
        'cheese_dismissed_trackers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('cheese_tracker_id', sa.String(length=64), nullable=False),
        sa.Column('dismissed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'cheese_tracker_id', name='_user_dismissed_tracker_uc'),
    )
    op.create_index(
        op.f('ix_cheese_dismissed_trackers_user_id'),
        'cheese_dismissed_trackers',
        ['user_id'],
        unique=False,
    )

    # Backfill: everything currently attached to a Cheese tracker keeps behaving
    # as it does today, which is to say it is mirrored.
    op.execute(
        """
        UPDATE user_room_subscriptions
           SET cheese_link = 'linked'
         WHERE room_id IN (
                SELECT id FROM tracked_rooms WHERE cheese_tracker_id IS NOT NULL
         )
        """
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_cheese_dismissed_trackers_user_id'),
        table_name='cheese_dismissed_trackers',
    )
    op.drop_table('cheese_dismissed_trackers')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('cheese_last_sync_unlisted')
        batch_op.drop_column('cheese_publish_new_rooms')

    with op.batch_alter_table('user_room_subscriptions', schema=None) as batch_op:
        batch_op.drop_column('cheese_unlisted_at')
        batch_op.drop_column('cheese_link')
