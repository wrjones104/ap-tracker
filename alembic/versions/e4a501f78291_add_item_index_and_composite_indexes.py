"""add_item_index_and_composite_indexes

Revision ID: e4a501f78291
Revises: f92a101b1a20
Create Date: 2026-07-30 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4a501f78291'
down_revision: Union[str, Sequence[str], None] = 'f92a101b1a20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('notified_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('item_index', sa.Integer(), nullable=True))
        batch_op.create_index('ix_notifieditem_item_index', ['item_index'], unique=False)
        batch_op.create_index('ix_notifieditem_room_receiving_time', ['room_id', 'receiving_slot_id', 'timestamp'], unique=False)
        batch_op.create_unique_constraint('_item_event_index_uc', ['room_id', 'receiving_slot_id', 'item_index'])

    with op.batch_alter_table('notified_hints', schema=None) as batch_op:
        batch_op.create_index('ix_notifiedhint_room_owner_time', ['room_id', 'item_owner_id', 'timestamp'], unique=False)

    with op.batch_alter_table('user_tracked_slots', schema=None) as batch_op:
        batch_op.create_index('ix_usertrackedslot_user_room', ['user_id', 'room_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('user_tracked_slots', schema=None) as batch_op:
        batch_op.drop_index('ix_usertrackedslot_user_room')

    with op.batch_alter_table('notified_hints', schema=None) as batch_op:
        batch_op.drop_index('ix_notifiedhint_room_owner_time')

    with op.batch_alter_table('notified_items', schema=None) as batch_op:
        batch_op.drop_constraint('_item_event_index_uc', type_='unique')
        batch_op.drop_index('ix_notifieditem_room_receiving_time')
        batch_op.drop_index('ix_notifieditem_item_index')
        batch_op.drop_column('item_index')
