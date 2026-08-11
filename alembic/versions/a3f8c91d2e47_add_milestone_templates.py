"""add_milestone_templates

Revision ID: a3f8c91d2e47
Revises: f92a101b1a20
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f8c91d2e47'
down_revision: Union[str, Sequence[str], None] = 'f92a101b1a20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'milestone_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('game_name', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'game_name', 'name', name='_user_game_template_uc'),
    )
    op.create_index('ix_milestone_templates_user_id', 'milestone_templates', ['user_id'])
    op.create_index('ix_milestone_templates_game_name', 'milestone_templates', ['game_name'])

    op.create_table(
        'milestone_template_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=False),
        sa.Column('item_name', sa.String(length=255), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_group', sa.Boolean(), nullable=False, server_default='f'),
        sa.ForeignKeyConstraint(['template_id'], ['milestone_templates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('milestone_template_items')
    op.drop_index('ix_milestone_templates_game_name', table_name='milestone_templates')
    op.drop_index('ix_milestone_templates_user_id', table_name='milestone_templates')
    op.drop_table('milestone_templates')
