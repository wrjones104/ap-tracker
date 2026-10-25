"""add device data_only_push

Every push carries a notification block, so while the app is in the background
Android's Firebase library draws it and the app's code never runs: no Snooze
buttons, no widget update (#501). An app that can draw a push itself reports so
when it registers the device, and the server then sends it data-only messages.

devices.data_only_push records that report. False for every existing row, which
is what every installed app should get; nothing to backfill.

Revision ID: d8e3f1a6b2c4
Revises: c5d82a4f1e90
Create Date: 2026-10-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e3f1a6b2c4'
down_revision: Union[str, Sequence[str], None] = 'c5d82a4f1e90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'devices',
        sa.Column('data_only_push', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('devices', 'data_only_push')
