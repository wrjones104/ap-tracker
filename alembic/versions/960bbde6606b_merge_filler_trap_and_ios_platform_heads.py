"""merge filler trap and ios platform heads

Revision ID: 960bbde6606b
Revises: 6aa084c2474f, a971160f9c05
Create Date: 2026-07-29 11:07:08.058764

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '960bbde6606b'
down_revision: Union[str, Sequence[str], None] = ('6aa084c2474f', 'a971160f9c05')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
