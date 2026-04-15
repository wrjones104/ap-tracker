"""update datapackage cache constraint

Revision ID: e62cbad2759c
Revises: bd1c7ba2707e
Create Date: 2026-04-15 11:17:52.046581

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e62cbad2759c'
down_revision: Union[str, Sequence[str], None] = 'bd1c7ba2707e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite does not support dropping constraints easily, so we usually use batch_alter_table
    # But first, we need to deduplicate existing rows that would violate the new constraint!
    # The new constraint is unique on (checksum, entity_type, entity_id). We keep the row with the min(id).

    conn = op.get_bind()
    conn.execute(sa.text("""
        DELETE FROM datapackage_cache
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM datapackage_cache
            GROUP BY checksum, entity_type, entity_id
        )
    """))

    with op.batch_alter_table('datapackage_cache', schema=None) as batch_op:
        batch_op.drop_constraint('_game_checksum_entity_uc', type_='unique')
        batch_op.create_unique_constraint('_checksum_entity_uc', ['checksum', 'entity_type', 'entity_id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('datapackage_cache', schema=None) as batch_op:
        batch_op.drop_constraint('_checksum_entity_uc', type_='unique')
        batch_op.create_unique_constraint('_game_checksum_entity_uc', ['game', 'checksum', 'entity_type', 'entity_id'])
