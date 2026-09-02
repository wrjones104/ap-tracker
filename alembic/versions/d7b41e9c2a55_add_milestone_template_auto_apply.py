"""add milestone template auto-apply

Adds the two columns behind "always add this template to new slots I play":

  milestone_templates.auto_apply        -- the user's per-template switch
  user_tracked_slots.auto_apply_pending -- set when a slot is newly tracked in
                                           'play' mode, cleared by the first poll
                                           that resolves the slot's game

Both existing-row defaults are false, so this migration is behavior-neutral:
no template auto-applies until the user turns one on, and no slot already in a
library is ever back-filled. Auto-apply is forward-only by construction.

Revision ID: d7b41e9c2a55
Revises: c4f8a1e07b3d
Create Date: 2026-09-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7b41e9c2a55'
down_revision: Union[str, Sequence[str], None] = 'c4f8a1e07b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('milestone_templates', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'auto_apply',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ))

    with op.batch_alter_table('user_tracked_slots', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'auto_apply_pending',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ))


def downgrade() -> None:
    with op.batch_alter_table('user_tracked_slots', schema=None) as batch_op:
        batch_op.drop_column('auto_apply_pending')

    with op.batch_alter_table('milestone_templates', schema=None) as batch_op:
        batch_op.drop_column('auto_apply')
