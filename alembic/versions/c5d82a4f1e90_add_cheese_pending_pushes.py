"""add cheese pending pushes

A slot claim or release that failed to reach Cheese Tracker was lost. The slot
route commits locally and pushes afterwards, so when the push timed out the app
said Playing while the slot stayed open on Cheese, and nothing reconciled. Worse,
the next poll saw the slot unclaimed and demoted it to watch with a "Slot
Released" push, as if the user had let it go. See #304.

cheese_pending_pushes remembers which slots still need a push, so the poller can
retry them on its next successful poll of that tracker. New table only; nothing
existing changes and there is nothing to backfill.

Revision ID: c5d82a4f1e90
Revises: a3e71c94b8d2
Create Date: 2026-09-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5d82a4f1e90'
down_revision: Union[str, Sequence[str], None] = 'a3e71c94b8d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cheese_pending_pushes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('cheese_tracker_id', sa.String(length=64), nullable=False),
        sa.Column('slot_id', sa.Integer(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cheese_tracker_id', 'user_id', 'slot_id', name='_cheese_pending_push_uc'),
    )


def downgrade() -> None:
    op.drop_table('cheese_pending_pushes')
