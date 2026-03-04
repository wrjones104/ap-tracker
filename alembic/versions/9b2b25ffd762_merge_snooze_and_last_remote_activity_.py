"""merge snooze and last_remote_activity heads

Revision ID: 9b2b25ffd762
Revises: 2a96c4d3bd18, fc573f17b4d6
Create Date: 2026-03-03 09:04:41.148673

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b2b25ffd762'
down_revision: Union[str, Sequence[str], None] = ('2a96c4d3bd18', 'fc573f17b4d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
