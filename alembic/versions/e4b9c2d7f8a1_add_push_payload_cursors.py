"""add push payload cursors

A push's item payload (#416) only helped when the phone could prove nothing came
between what it had and what the push carried. Items that arrive without a
notification of their own (filler and traps, by default) and hint changes in
polls that sent the user nothing broke that proof, so the phone had to sync
anyway. The server now remembers what the last payload carried, per user:

- user_tracked_slots.push_item_cursor: the newest item id carried for the slot.
- user_room_subscriptions.push_hint_cursor: the newest hint change carried for
  the hints touching the user's tracked slots in the room.

The next payload carries everything after them. Null means unknown, which is
every existing row: the next payload then starts from the poll before it, as
before. Nothing to backfill.

Revision ID: e4b9c2d7f8a1
Revises: d8e3f1a6b2c4
Create Date: 2026-10-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4b9c2d7f8a1'
down_revision: Union[str, Sequence[str], None] = 'd8e3f1a6b2c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_tracked_slots', sa.Column('push_item_cursor', sa.Integer(), nullable=True))
    op.add_column('user_room_subscriptions', sa.Column('push_hint_cursor', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('user_room_subscriptions', 'push_hint_cursor')
    op.drop_column('user_tracked_slots', 'push_item_cursor')
