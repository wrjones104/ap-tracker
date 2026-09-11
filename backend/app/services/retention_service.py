"""Automated retention purges.

Every function here deletes in bounded batches, committing as it goes, and stops
at a per-run cap rather than running to completion. Two reasons. The tables are
ones the poller writes to continuously, so a single long DELETE would hold locks
and queue writers behind it. And the first run after this shipped had years of
backlog to get through, which no single transaction should attempt.

A run that hits its cap leaves the rest for the next one. The caller gets
`more_remaining` so it can say so in the logs.
"""
import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import or_

from app import Session
from app.models import (
    NotifiedItem, NotifiedHint, User, JWTBlocklist, TrackedRoom,
)

# Rows per transaction. Small enough that the poller never waits long on a lock,
# large enough that the round trips do not dominate.
PURGE_BATCH_SIZE = 5000

# Ceiling per table per run. At a 24 hour cadence this clears roughly 200k rows
# a day per table, which is far above the rate they accumulate, so steady state
# never comes close. It only bites while working through a backlog.
PURGE_MAX_ROWS_PER_RUN = 200_000


def get_retention_days():
    """Days of history to keep. RETENTION_DAYS overrides the 90 day default."""
    try:
        value = int(os.environ.get('RETENTION_DAYS', '90'))
    except (TypeError, ValueError):
        logging.warning("[RETENTION] RETENTION_DAYS is not an integer; using 90.")
        return 90
    if value < 1:
        logging.warning("[RETENTION] RETENTION_DAYS below 1; using 90.")
        return 90
    return value


def get_guest_inactivity_days():
    """Days before an inactive guest account is removed.

    Deliberately not RETENTION_DAYS. That one governs how much history we keep,
    and an operator tightening it to reclaim disk must not discover it deleted
    user accounts as a side effect: a guest purge takes the account's
    subscriptions, tracked slots and devices with it through cascades, and none
    of that comes back. The floor is there for the same reason.
    """
    try:
        value = int(os.environ.get('GUEST_INACTIVITY_DAYS', '90'))
    except (TypeError, ValueError):
        logging.warning("[RETENTION] GUEST_INACTIVITY_DAYS is not an integer; using 90.")
        return 90
    if value < 30:
        logging.warning("[RETENTION] GUEST_INACTIVITY_DAYS below 30; using 90.")
        return 90
    return value


def _purge_in_batches(session, model, predicate, max_rows=None, batch_size=None):
    """Delete rows matching `predicate` in committed batches.

    Selects a bounded set of primary keys, deletes exactly those, commits, and
    repeats. Returns (rows_deleted, more_remaining).

    The two limits are resolved from the module globals here rather than bound as
    default arguments, so that changing the constants actually changes behaviour
    instead of being frozen at import time.
    """
    max_rows = PURGE_MAX_ROWS_PER_RUN if max_rows is None else max_rows
    batch_size = PURGE_BATCH_SIZE if batch_size is None else batch_size

    deleted = 0
    while deleted < max_rows:
        remaining_budget = min(batch_size, max_rows - deleted)
        ids = [row[0] for row in session.query(model.id)
               .filter(predicate)
               .limit(remaining_budget)
               .all()]
        if not ids:
            return deleted, False

        removed = session.query(model).filter(model.id.in_(ids)).delete(
            synchronize_session=False
        )
        session.commit()
        deleted += removed

        if len(ids) < remaining_budget:
            # The source query could not fill a batch, so nothing is left.
            return deleted, False

    # Stopped on the cap rather than on an empty result.
    return deleted, True


def purge_expired_notification_events(retention_days=None):
    """Purge NotifiedItem and NotifiedHint rows older than the retention window.

    SlotItemCount is deliberately untouched. It is the authority for milestone
    progress precisely because it outlives this window, and it is never
    recomputed downward from what survives here. See reconcile_slot_item_counts
    in threshold_service for the matching guarantee on the other side.
    """
    if retention_days is None:
        retention_days = get_retention_days()

    session = Session()
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

        deleted_items, items_remaining = _purge_in_batches(
            session, NotifiedItem, NotifiedItem.timestamp < cutoff_date
        )
        deleted_hints, hints_remaining = _purge_in_batches(
            session, NotifiedHint, NotifiedHint.timestamp < cutoff_date
        )

        if deleted_items or deleted_hints:
            logging.info(
                "[RETENTION] Purged %s items and %s hints older than %s days.%s",
                deleted_items, deleted_hints, retention_days,
                " More remain for the next run." if (items_remaining or hints_remaining) else "",
            )
        return {
            'purged_items': deleted_items,
            'purged_hints': deleted_hints,
            'events_remaining': items_remaining or hints_remaining,
        }
    except Exception as e:
        session.rollback()
        logging.error(f"[RETENTION_ERROR] Failed to purge notification events: {e}", exc_info=True)
        return {'purged_items': 0, 'purged_hints': 0, 'events_remaining': False}
    finally:
        Session.remove()


def purge_orphaned_room_events():
    """Purge history whose room no longer exists.

    notified_items and notified_hints key on the room's UUID string with no
    foreign key, so nothing removed them when a room was deleted. They are
    unreachable: every read path joins through a room the caller is subscribed
    to. Production held 454,018 such item rows when this was written.
    """
    session = Session()
    try:
        # Resolved once, rather than as a NOT EXISTS inside the batch predicate.
        # notified_items.room_id has no index that helps an anti-join against the
        # whole of tracked_rooms, so that form re-scanned a 977 MB heap for every
        # batch, up to forty times per table per run. Deleting by a known room
        # list rides ix_notified_items_room_id instead, and the one distinct scan
        # replaces all of them.
        live_rooms = {r[0] for r in session.query(TrackedRoom.room_id).all()}

        dead_item_rooms = [
            r[0] for r in session.query(NotifiedItem.room_id).distinct().all()
            if r[0] not in live_rooms
        ]
        dead_hint_rooms = [
            r[0] for r in session.query(NotifiedHint.room_id).distinct().all()
            if r[0] not in live_rooms
        ]

        if dead_item_rooms:
            deleted_items, items_remaining = _purge_in_batches(
                session, NotifiedItem, NotifiedItem.room_id.in_(dead_item_rooms)
            )
        else:
            deleted_items, items_remaining = 0, False

        if dead_hint_rooms:
            deleted_hints, hints_remaining = _purge_in_batches(
                session, NotifiedHint, NotifiedHint.room_id.in_(dead_hint_rooms)
            )
        else:
            deleted_hints, hints_remaining = 0, False

        if deleted_items or deleted_hints:
            logging.info(
                "[RETENTION] Purged %s orphaned items and %s orphaned hints.%s",
                deleted_items, deleted_hints,
                " More remain for the next run." if (items_remaining or hints_remaining) else "",
            )
        return {
            'purged_orphan_items': deleted_items,
            'purged_orphan_hints': deleted_hints,
            'orphans_remaining': items_remaining or hints_remaining,
        }
    except Exception as e:
        session.rollback()
        logging.error(f"[RETENTION_ERROR] Failed to purge orphaned room events: {e}", exc_info=True)
        return {'purged_orphan_items': 0, 'purged_orphan_hints': 0, 'orphans_remaining': False}
    finally:
        Session.remove()


def purge_inactive_guest_accounts(inactivity_days=None):
    """
    Purges guest accounts (is_guest == True) with no activity for >inactivity_days.
    Cascading deletes remove associated subscriptions, slots, devices, ignore lists, etc.
    """
    if inactivity_days is None:
        inactivity_days = get_guest_inactivity_days()

    session = Session()
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=inactivity_days)

        inactive_guests = session.query(User).filter(
            User.is_guest == True,
            or_(User.last_activity < cutoff_date, User.last_activity == None)
        ).all()

        deleted_count = len(inactive_guests)
        for user in inactive_guests:
            session.delete(user)

        session.commit()
        if deleted_count:
            logging.info(f"[RETENTION] Purged {deleted_count} inactive guest accounts (inactive for >{inactivity_days} days).")
        return {'purged_guests': deleted_count}
    except Exception as e:
        session.rollback()
        logging.error(f"[RETENTION_ERROR] Failed to purge guest accounts: {e}", exc_info=True)
        return {'purged_guests': 0}
    finally:
        Session.remove()


def purge_expired_jwt_blocklist():
    """
    Purges JWT tokens from the blocklist whose expiration date has passed.
    """
    session = Session()
    try:
        now = datetime.utcnow()
        deleted = session.query(JWTBlocklist).filter(
            JWTBlocklist.expires_at < now
        ).delete(synchronize_session=False)

        session.commit()
        if deleted > 0:
            logging.info(f"[RETENTION] Purged {deleted} expired JWT blocklist entries.")
        return {'purged_jwts': deleted}
    except Exception as e:
        session.rollback()
        logging.error(f"[RETENTION_ERROR] Failed to purge JWT blocklist: {e}", exc_info=True)
        return {'purged_jwts': 0}
    finally:
        Session.remove()


def run_all_retention_tasks(retention_days=None):
    """Runs all retention cleanup operations.

    Each step owns its own session and commits its own work, so one failing does
    not cost the others theirs. That is deliberate: the arrangement this replaced
    put unrelated deletions in a single transaction, and a foreign key violation
    in one half silently discarded the other.

    Each call is also guarded here, not only inside the function. The inner
    handlers catch database errors, which is what actually goes wrong, but they
    cannot catch something raised before their own try block. Without this the
    first unexpected failure would skip every step after it, and the steps are
    ordered by cost rather than importance.
    """
    if retention_days is None:
        retention_days = get_retention_days()

    # No argument to the guest purge: guest lifetime is its own setting, not a
    # slice of the history window. See get_guest_inactivity_days.
    steps = (
        ('orphaned room events', purge_orphaned_room_events),
        ('expired notification events',
         lambda: purge_expired_notification_events(retention_days=retention_days)),
        ('inactive guest accounts', purge_inactive_guest_accounts),
        ('expired JWT blocklist', purge_expired_jwt_blocklist),
    )

    results = {}
    for label, step in steps:
        try:
            results.update(step() or {})
        except Exception as e:
            logging.error(
                "[RETENTION_ERROR] Step '%s' failed; continuing with the rest: %s",
                label, e, exc_info=True,
            )
    return results
