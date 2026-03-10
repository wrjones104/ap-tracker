"""rename android_id to device_id

Revision ID: 481936e4f29e
Revises: bd1c7ba2707e
Create Date: 2026-03-10 01:08:10.409185

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '481936e4f29e'
down_revision: Union[str, Sequence[str], None] = 'bd1c7ba2707e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use raw SQL to rename the column because sqlite batch alter gets tricky with constraints and indexes sometimes
    with op.get_context().autocommit_block():
        op.execute('ALTER TABLE devices RENAME COLUMN android_id TO device_id')
        op.execute('DROP INDEX IF EXISTS ix_devices_android_id')
        op.execute('CREATE INDEX ix_devices_device_id ON devices (device_id)')


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute('ALTER TABLE devices RENAME COLUMN device_id TO android_id')
        op.execute('DROP INDEX IF EXISTS ix_devices_device_id')
        op.execute('CREATE INDEX ix_devices_android_id ON devices (android_id)')
