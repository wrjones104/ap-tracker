"""clear pinned notify_finished overrides on CT-synced slots

Cheese Tracker sync used to stamp User.notify_finished_default into
UserTrackedSlot.notify_finished as a concrete per-slot override, while the app's
slot picker left it NULL (inherit). The two creation paths disagreed, so slots
that arrived via CT sync stopped following later changes to the user's global
"notify about finished slots" setting.

The stamping is fixed at the creation site. This clears the rows it already
wrote, so they go back to inheriting.

Only rows whose override still equals the owning user's current default are
cleared. A row the user deliberately set to something other than their default
is a real choice and is left alone. A row they deliberately set to the same
value as their default is indistinguishable from a stamped one, but the two are
behaviorally identical until the default changes, so clearing it is safe.

Revision ID: c4f8a1e07b3d
Revises: a7c3e91b45d2
Create Date: 2026-08-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f8a1e07b3d'
down_revision: Union[str, Sequence[str], None] = 'a7c3e91b45d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        UPDATE user_tracked_slots
           SET notify_finished = NULL
         WHERE notify_finished IS NOT NULL
           AND EXISTS (
               SELECT 1
                 FROM users
                WHERE users.id = user_tracked_slots.user_id
                  AND users.notify_finished_default = user_tracked_slots.notify_finished
           )
    """))


def downgrade() -> None:
    # Not reversible: once an override is cleared there is no record of which
    # rows carried one, and re-stamping every slot would recreate the bug this
    # migration exists to undo.
    pass
