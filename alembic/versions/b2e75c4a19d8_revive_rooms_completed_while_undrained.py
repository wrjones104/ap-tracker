"""revive rooms marked complete while still undrained

One-off reconciliation for issue #263.

Until this release, `tracked_rooms.is_complete` was set as soon as every slot
had goaled. In a room with release disabled, goaling leaves a player's remaining
locations unchecked and they keep playing so other players still receive their
items. Those rooms were marked complete while still active, and because every
room-selection query filters `is_complete == False` and nothing ever resets the
column, they stopped being polled permanently.

The poller now also requires the room to be drained. That fixes rooms going
forward but does nothing for rooms already stuck, since nothing will ever poll
them again on its own.

Scope is deliberately narrow: only rooms that are not suspended and had remote
activity inside the 30-day stale window. Anything older is either genuinely
finished or already abandoned, and `db_check_stale_rooms` is the backstop for
whatever this revives in error -- a revived room that sees no further activity
is suspended on the next stale sweep.

Revived rooms also get `needs_backfill` set on their tracked slots, so the first
poll after revival ingests the backlog silently instead of notifying on every
item sent while the room was dark.

Rooms completed before the completion facts existed carry no `has_all_checks`
key at all. Those are revived too: one poll computes the facts and immediately
re-completes the room if it really was drained, which is both self-correcting
and the only way to reach the rooms that were stuck longest.

Revision ID: b2e75c4a19d8
Revises: c4d21a7f9b83
Create Date: 2026-08-19 00:00:00.000000

"""
import json
import logging
from datetime import datetime, timedelta
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2e75c4a19d8'
down_revision: Union[str, Sequence[str], None] = 'c4d21a7f9b83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STALE_WINDOW_DAYS = 30


def _is_drained(cached_players_json):
    """
    True only when every slot is known to have nothing left to send.

    Returns False both for "some slot still has checks out" and for "we have no
    completion facts for this room", which are the two cases worth reviving.
    """
    try:
        players = json.loads(cached_players_json or '[]')
    except (ValueError, TypeError):
        return False
    if not isinstance(players, list) or not players:
        return False
    for player in players:
        if not isinstance(player, dict) or 'has_all_checks' not in player:
            return False
        if not player.get('has_all_checks'):
            return False
    return True


def upgrade() -> None:
    bind = op.get_bind()
    cutoff = datetime.utcnow() - timedelta(days=STALE_WINDOW_DAYS)

    rooms = bind.execute(sa.text("""
        SELECT id, cached_players_json
        FROM tracked_rooms
        WHERE is_complete
          AND NOT is_suspended
          AND last_remote_activity IS NOT NULL
          AND last_remote_activity > :cutoff
    """), {'cutoff': cutoff}).fetchall()

    revive_ids = [row[0] for row in rooms if not _is_drained(row[1])]

    if revive_ids:
        # Chunked so a large backlog does not build one enormous IN list.
        for start in range(0, len(revive_ids), 500):
            chunk = revive_ids[start:start + 500]
            bind.execute(
                sa.text("UPDATE tracked_rooms SET is_complete = false WHERE id IN :ids")
                .bindparams(sa.bindparam('ids', expanding=True)),
                {'ids': chunk},
            )
            # Make the catch-up poll silent. These rooms have been dark for up to 30
            # days, so the first poll after revival sees every item sent in the
            # meantime as brand new and would notify on all of it. needs_backfill is
            # the existing mechanism for exactly this -- the poller suppresses item,
            # hint, milestone, and finish notifications for a flagged slot and clears
            # the flag at the end of that poll, so this costs one quiet cycle.
            bind.execute(
                sa.text("UPDATE user_tracked_slots SET needs_backfill = true WHERE room_id IN :ids")
                .bindparams(sa.bindparam('ids', expanding=True)),
                {'ids': chunk},
            )

    logging.info(
        "[MIGRATION b2e75c4a19d8] Revived %d of %d recently-active completed rooms "
        "that were not fully drained.",
        len(revive_ids), len(rooms),
    )


def downgrade() -> None:
    # Not reversible: which rooms this revived is not recorded, and re-marking
    # them complete would reintroduce the bug. The poller re-completes any room
    # that genuinely is done on its next poll.
    pass
