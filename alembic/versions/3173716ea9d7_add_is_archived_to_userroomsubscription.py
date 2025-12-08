"""Add is_archived to UserRoomSubscription

Revision ID: 3173716ea9d7
Revises: ed960a254a42
Create Date: 2025-12-07 19:51:33.125825

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3173716ea9d7'
down_revision: Union[str, Sequence[str], None] = 'ed960a254a42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Add 'is_archived' column to 'user_room_subscriptions' table
    # defaulting to False (active)
    op.add_column('user_room_subscriptions', sa.Column('is_archived', sa.Boolean(), server_default='f', nullable=False))

def downgrade():
    # Remove the column if we need to roll back
    op.drop_column('user_room_subscriptions', 'is_archived')
