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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'notified_items' in existing_tables:
        items_cols = [c['name'] for c in inspector.get_columns('notified_items')]
        items_idx = [i['name'] for i in inspector.get_indexes('notified_items')]
        items_uc = [c['name'] for c in inspector.get_unique_constraints('notified_items')]

        with op.batch_alter_table('notified_items', schema=None) as batch_op:
            if 'item_index' not in items_cols:
                batch_op.add_column(sa.Column('item_index', sa.Integer(), nullable=True))
            if 'ix_notifieditem_item_index' not in items_idx:
                batch_op.create_index('ix_notifieditem_item_index', ['item_index'], unique=False)
            if 'ix_notifieditem_room_receiving_time' not in items_idx:
                batch_op.create_index('ix_notifieditem_room_receiving_time', ['room_id', 'receiving_slot_id', 'timestamp'], unique=False)
            if '_item_event_index_uc' not in items_uc:
                batch_op.create_unique_constraint('_item_event_index_uc', ['room_id', 'receiving_slot_id', 'item_index'])

    if 'notified_hints' in existing_tables:
        hints_idx = [i['name'] for i in inspector.get_indexes('notified_hints')]
        with op.batch_alter_table('notified_hints', schema=None) as batch_op:
            if 'ix_notifiedhint_room_owner_time' not in hints_idx:
                batch_op.create_index('ix_notifiedhint_room_owner_time', ['room_id', 'item_owner_id', 'timestamp'], unique=False)

    if 'user_tracked_slots' in existing_tables:
        slots_idx = [i['name'] for i in inspector.get_indexes('user_tracked_slots')]
        with op.batch_alter_table('user_tracked_slots', schema=None) as batch_op:
            if 'ix_usertrackedslot_user_room' not in slots_idx:
                batch_op.create_index('ix_usertrackedslot_user_room', ['user_id', 'room_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'user_tracked_slots' in existing_tables:
        slots_idx = [i['name'] for i in inspector.get_indexes('user_tracked_slots')]
        with op.batch_alter_table('user_tracked_slots', schema=None) as batch_op:
            if 'ix_usertrackedslot_user_room' in slots_idx:
                batch_op.drop_index('ix_usertrackedslot_user_room')

    if 'notified_hints' in existing_tables:
        hints_idx = [i['name'] for i in inspector.get_indexes('notified_hints')]
        with op.batch_alter_table('notified_hints', schema=None) as batch_op:
            if 'ix_notifiedhint_room_owner_time' in hints_idx:
                batch_op.drop_index('ix_notifiedhint_room_owner_time')

    if 'notified_items' in existing_tables:
        items_cols = [c['name'] for c in inspector.get_columns('notified_items')]
        items_idx = [i['name'] for i in inspector.get_indexes('notified_items')]
        items_uc = [c['name'] for c in inspector.get_unique_constraints('notified_items')]

        with op.batch_alter_table('notified_items', schema=None) as batch_op:
            if '_item_event_index_uc' in items_uc:
                batch_op.drop_constraint('_item_event_index_uc', type_='unique')
            if 'ix_notifieditem_room_receiving_time' in items_idx:
                batch_op.drop_index('ix_notifieditem_room_receiving_time')
            if 'ix_notifieditem_item_index' in items_idx:
                batch_op.drop_index('ix_notifieditem_item_index')
            if 'item_index' in items_cols:
                batch_op.drop_column('item_index')

