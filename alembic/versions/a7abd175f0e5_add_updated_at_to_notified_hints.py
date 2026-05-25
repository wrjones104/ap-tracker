"""add_updated_at_to_notified_hints

Revision ID: a7abd175f0e5
Revises: c1b75abc079d
Create Date: 2026-05-23 18:49:11.796412

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7abd175f0e5'
down_revision: Union[str, Sequence[str], None] = 'c1b75abc079d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use batch_alter_table to safely add column as nullable first to support SQLite
    with op.batch_alter_table('notified_hints') as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
    
    # Backfill with the creation timestamp so existing hints retain correct sync context
    op.execute("UPDATE notified_hints SET updated_at = timestamp")
    
    # Make the column NOT NULL now that it is backfilled, and add the index
    with op.batch_alter_table('notified_hints') as batch_op:
        batch_op.alter_column('updated_at', nullable=False, existing_type=sa.DateTime())
        batch_op.create_index('ix_notified_hints_updated_at', ['updated_at'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('notified_hints') as batch_op:
        batch_op.drop_index('ix_notified_hints_updated_at')
        batch_op.drop_column('updated_at')


