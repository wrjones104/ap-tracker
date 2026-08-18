"""add user defined finished definition

Adds the plumbing for user-configurable "finished" semantics:
  - users.finished_definition_default        (global default, 'goal')
  - user_tracked_slots.finished_definition   (nullable per-slot override)
  - tracked_rooms.cached_checks_json         ({slot_id: checks_done_count})

Existing rows default to 'goal', which is the behavior the app has always had,
so this migration is behavior-neutral on its own.

Revision ID: c4d21a7f9b83
Revises: a3f8c91d2e47
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d21a7f9b83'
down_revision: Union[str, Sequence[str], None] = 'a3f8c91d2e47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'finished_definition_default',
            sa.String(length=16),
            nullable=False,
            server_default='goal',
        ))

    with op.batch_alter_table('user_tracked_slots', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'finished_definition',
            sa.String(length=16),
            nullable=True,
        ))

    with op.batch_alter_table('tracked_rooms', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'cached_checks_json',
            sa.String(),
            nullable=True,
            server_default='{}',
        ))


def downgrade() -> None:
    with op.batch_alter_table('tracked_rooms', schema=None) as batch_op:
        batch_op.drop_column('cached_checks_json')

    with op.batch_alter_table('user_tracked_slots', schema=None) as batch_op:
        batch_op.drop_column('finished_definition')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('finished_definition_default')
