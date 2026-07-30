"""add_user_whitelist_items

Revision ID: f92a101b1a20
Revises: 960bbde6606b
Create Date: 2026-07-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f92a101b1a20'
down_revision: Union[str, Sequence[str], None] = '960bbde6606b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_whitelist_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('item_name', sa.String(length=255), nullable=False),
        sa.Column('game_name', sa.String(length=255), nullable=True),
        sa.Column('is_group', sa.Boolean(), server_default='f', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'item_name', 'game_name', name='_user_whitelist_item_uc')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('user_whitelist_items')
