"""merge all heads

Revision ID: c1b75abc079d
Revises: 12b94b17380c, 5427fbf85337
Create Date: 2026-05-17 18:11:29.461234

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1b75abc079d'
down_revision: Union[str, Sequence[str], None] = ('12b94b17380c', '5427fbf85337')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
