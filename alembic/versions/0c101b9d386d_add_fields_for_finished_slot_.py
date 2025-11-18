"""Add fields for finished slot notifications

Revision ID: 0c101b9d386d
Revises: 9a754af588ad
Create Date: 2025-11-17 10:51:50.818439

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0c101b9d386d'
down_revision: Union[str, Sequence[str], None] = '9a754af588ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add 'notify_finished' to 'user_tracked_slots'.
    # CRITICAL CHANGE: nullable=True allows existing rows to have NULL here.
    with op.batch_alter_table('user_tracked_slots', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notify_finished', sa.Boolean(), nullable=True))

    # 2. Add 'notify_finished_default' to 'users'.
    # CRITICAL CHANGE: server_default=sa.true() fills existing rows with TRUE.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notify_finished_default', sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('notify_finished_default')

    with op.batch_alter_table('user_tracked_slots', schema=None) as batch_op:
        batch_op.drop_column('notify_finished')