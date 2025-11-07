"""Add cheese_tracker_id to TrackedRoom

Revision ID: c6c4df853824
Revises: 17099a792d8b
Create Date: 2025-11-06 14:36:31.706945

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6c4df853824'
down_revision: Union[str, Sequence[str], None] = '17099a792d8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Don't use unique=True directly in add_column for standard SQLite batch operations
    with op.batch_alter_table('tracked_rooms', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cheese_tracker_id', sa.String(), nullable=True))
        # Explicitly add the unique constraint with a name
        batch_op.create_unique_constraint('uq_tracked_room_cheese_id', ['cheese_tracker_id'])
def downgrade():
    with op.batch_alter_table('tracked_rooms', schema=None) as batch_op:
        # Drop it by name first
        batch_op.drop_constraint('uq_tracked_room_cheese_id', type_='unique')
        batch_op.drop_column('cheese_tracker_id')
