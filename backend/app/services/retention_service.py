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

import json

from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError

from app import Session
from app.models import (
    NotifiedItem, NotifiedHint, User, JWTBlocklist, TrackedRoom, CheesePendingPush,
    DatapackageCache,
)
from app.utils import room_checksums

# Rows per transaction. Small enough that the poller never waits long on a lock,
# large enough that the round trips do not dominate.
PURGE_BATCH_SIZE = 5000

# Ceiling per table per run. At a 24 hour cadence this clears roughly 200k rows
# a day per table, which is far above the rate they accumulate, so steady state
# never comes close. It only bites while working through a backlog.
PURGE_MAX_ROWS_PER_RUN = 200_000

# Guests committed per transaction. Far smaller than PURGE_BATCH_SIZE because a
# guest delete is not one row: it cascades into subscriptions, tracked slots,
# devices, ignore lists and more, so the write amplification per item is high.
GUEST_PURGE_BATCH_SIZE = 200

# Checksums per transaction, not rows. One checksum is every item and location
# name of one apworld build, which for a large game runs to tens of thousands
# of rows, so this number times a datapackage is the real batch size.
DATAPACKAGE_CHECKSUM_BATCH_SIZE = 25

# Ceiling per run, also in checksums. Production held 14,997,948 rows across
# the table when this was written, an unknown share of it unreferenced, so the
# first runs work through a backlog a few hundred checksums at a time.
DATAPACKAGE_MAX_CHECKSUMS_PER_RUN = 500

# Share of rooms whose game_checksums_json may be unreadable before the sweep
# refuses to run. See purge_unreferenced_datapackage_cache for why.
DATAPACKAGE_UNREADABLE_ABORT_RATIO = 0.10


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

        # Un-indexed rows are left alone. They predate the item_index migration,
        # and the poller owns their disposal: when a poll meets them it deletes
        # them AND resets that room's SlotItemCount, so the backfill that follows
        # rebuilds the counts from zero. Deleting them here skips that reset, and
        # a room revived afterwards would seed its counts from the surviving
        # SlotItemCount rows and then increment again, doubling them for good now
        # that nothing recomputes counts downward.
        #
        # Production had 3,060 rooms in exactly this state on 2026-09-11: all
        # suspended or complete, all with history carrying no index at all.
        deleted_items, items_remaining = _purge_in_batches(
            session, NotifiedItem,
            (NotifiedItem.timestamp < cutoff_date) & NotifiedItem.item_index.isnot(None)
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
    deleted_count = 0
    skipped_count = 0
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=inactivity_days)

        # Ids rather than instances. Each commit below expires every instance
        # still loaded, so holding User objects across the loop would issue a
        # reload per guest on next access.
        guest_ids = [
            row[0] for row in session.query(User.id).filter(
                User.is_guest == True,
                or_(User.last_activity < cutoff_date, User.last_activity == None)
            ).order_by(User.id).all()
        ]

        pending = 0
        for guest_id in guest_ids:
            # Locked, re-read and re-checked rather than trusted from the list.
            # The ids are taken once and worked through across several commits,
            # so under READ COMMITTED a guest selected at the start can upgrade
            # to Discord (auth.py flips is_guest on this same row) or open the
            # app (every authenticated request stamps last_activity) before its
            # turn comes. Deleting on the strength of the stale list would
            # cascade away a live account. The row lock holds the re-check true
            # until this batch commits; SQLite ignores FOR UPDATE.
            user = session.get(
                User, guest_id, with_for_update=True, populate_existing=True)
            if user is None or not user.is_guest:
                continue
            if user.last_activity is not None and user.last_activity >= cutoff_date:
                continue

            # A savepoint per guest, so an undeletable one costs itself and
            # nothing else. This used to be one loop behind one commit: #331 was
            # a guest owning a milestone template that had no cascade, and that
            # single row discarded every other guest in the run. Because the
            # selection is deterministic it then failed identically on every run
            # after it, and the only signal was one line a day in the logs.
            #
            # IntegrityError only. A row-level fault is a constraint the delete
            # cannot get past, and that is what this isolates. A dropped
            # connection or a lock timeout is not about this guest, and catching
            # it here would log once per remaining guest instead of stopping the
            # run once in the handler below.
            try:
                with session.begin_nested():
                    session.delete(user)
            except IntegrityError:
                skipped_count += 1
                logging.exception(
                    "[RETENTION] Could not delete guest %s; skipping it.", guest_id)
                continue

            pending += 1
            if pending >= GUEST_PURGE_BATCH_SIZE:
                session.commit()
                # Credited after the commit, not at the savepoint. A failed
                # commit rolls the whole batch back, and the count is what
                # purge_backlog.py prints to the operator.
                deleted_count += pending
                pending = 0

        if pending:
            session.commit()
            deleted_count += pending

        if deleted_count:
            logging.info(
                "[RETENTION] Purged %s inactive guest accounts (inactive for >%s days).",
                deleted_count, inactivity_days)
        if skipped_count:
            # A count, not a stack trace to go hunting for. A number that stays
            # the same day after day is the signal that something needs a
            # cascade.
            logging.warning(
                "[RETENTION] %s guest account(s) could not be deleted and were "
                "left in place.", skipped_count)
        return {'purged_guests': deleted_count, 'skipped_guests': skipped_count}
    except Exception as e:
        session.rollback()
        logging.error(f"[RETENTION_ERROR] Failed to purge guest accounts: {e}", exc_info=True)
        # Committed batches only; the rollback discarded the one in progress.
        return {'purged_guests': deleted_count, 'skipped_guests': skipped_count}
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


# A pending Cheese push is retried on its tracker's next poll and dropped after a
# few attempts, so a row this old belongs to a tracker nothing polls any more:
# unlinked, deleted, or merged away. See #304.
CHEESE_PENDING_PUSH_MAX_AGE_DAYS = 7


def purge_stale_cheese_pending_pushes():
    """
    Purges pending Cheese pushes whose tracker stopped being polled before they
    could be retried or given up on.
    """
    session = Session()
    try:
        cutoff = datetime.utcnow() - timedelta(days=CHEESE_PENDING_PUSH_MAX_AGE_DAYS)
        deleted = session.query(CheesePendingPush).filter(
            CheesePendingPush.created_at < cutoff
        ).delete(synchronize_session=False)

        session.commit()
        if deleted > 0:
            logging.info(f"[RETENTION] Purged {deleted} stale pending Cheese pushes.")
        return {'purged_cheese_pending_pushes': deleted}
    except Exception as e:
        session.rollback()
        logging.error(f"[RETENTION_ERROR] Failed to purge pending Cheese pushes: {e}", exc_info=True)
        return {'purged_cheese_pending_pushes': 0}
    finally:
        Session.remove()


# Walks the checksum index one value at a time, the loose index scan
# _DISTINCT_GAMES_SQL already uses for game names (#439), then joins each
# checksum to its own _metadata marker by full key. A plain DISTINCT over
# checksum reads one index entry per cached row -- 15M of them, 15s -- and the
# backlog drain runs this once per pass, not once per day. COALESCE covers a
# checksum whose download died before its marker row was written.
_CACHED_CHECKSUMS_SQL = text("""
    WITH RECURSIVE checksums(checksum) AS (
        SELECT MIN(checksum) FROM datapackage_cache
        UNION ALL
        SELECT (SELECT MIN(d.checksum) FROM datapackage_cache d
                 WHERE d.checksum > checksums.checksum)
        FROM checksums
        WHERE checksums.checksum IS NOT NULL
    )
    SELECT
        c.checksum,
        COALESCE(m.game, (SELECT d.game FROM datapackage_cache d
                           WHERE d.checksum = c.checksum LIMIT 1)) AS game,
        m.entity_name AS marker
    FROM checksums c
    LEFT JOIN datapackage_cache m
           ON m.checksum = c.checksum
          AND m.entity_type = '_metadata'
          AND m.entity_id = 0
    WHERE c.checksum IS NOT NULL
""")


def _salvage_checksums(raw):
    """Every valid checksum string in a row that room_checksums rejected."""
    try:
        parsed = json.loads(raw or '{}')
    except (ValueError, TypeError, RecursionError):
        return ()
    if not isinstance(parsed, dict):
        return ()
    return [value for value in parsed.values()
            if isinstance(value, str) and value.strip()]


def _collect_referenced_checksums(session):
    """(rooms, referenced checksums, ids of rooms whose json is unreadable).

    A partly broken row -- one game mapped to null, say -- still names real
    checksums, and room_checksums rejects the whole map rather than guess at
    it. Here that distinction matters more than it does for the cache check,
    because evicting a checksum such a room still needs is not recoverable:
    every path that would re-download it reads the same column and skips the
    room, so it polls on forever against a datapackage that is gone. The valid
    entries are therefore salvaged into the reference set, while the room still
    counts as unreadable for the warning and the abort ratio.
    """
    rooms = session.query(TrackedRoom.id, TrackedRoom.game_checksums_json).all()
    referenced = set()
    unreadable = []
    for room_db_id, raw in rooms:
        values = room_checksums(raw)
        if values is None:
            unreadable.append(room_db_id)
            referenced.update(_salvage_checksums(raw))
            continue
        referenced.update(values)
    return rooms, referenced, unreadable


def _plan_datapackage_eviction(session):
    """(rooms, referenced, unreadable, checksums the sweep would evict).

    Reads the cache before the rooms. A room set up between the two reads then
    appears in the reference set but not in the cache snapshot, and the worst
    that costs is keeping its datapackage one run longer. The other order loses
    it: the room is absent from the reference set while the checksums its setup
    just wrote are present in the snapshot.
    """
    cached_rows = session.execute(_CACHED_CHECKSUMS_SQL).all()
    rooms, referenced, unreadable = _collect_referenced_checksums(session)

    cached = set()
    games_in_play = set()
    candidates = {}
    for checksum, game, marker in cached_rows:
        cached.add(checksum)
        if checksum in referenced:
            if game:
                games_in_play.add(game)
        elif game:
            candidates.setdefault(game, []).append(
                (marker == '_completed_v2', marker is not None, checksum))

    # One build of every game no room plays survives the sweep. GET /games and
    # GET /games/<game>/items are served from this table and nothing else, and
    # the milestone, ignore-list and whitelist editors read them for games the
    # user has never tracked -- deliberately, so a template does not require
    # having played the game. The iOS guide documents /games as "every game
    # name the server knows", and that client cannot be updated. Evicting a
    # game's last build would quietly drop it from all of them.
    #
    # The cost is one datapackage per game, roughly 2,400, against every older
    # build of every game, which is what the table actually grew on. Preferring
    # a _completed_v2 marker and then the highest checksum keeps the choice
    # deterministic, so repeated drain passes converge instead of trading one
    # survivor for another.
    keep = set()
    for game, builds in candidates.items():
        if game not in games_in_play:
            keep.add(max(builds)[2])

    return rooms, referenced, unreadable, sorted(cached - referenced - keep)


def survey_unreferenced_datapackage_cache(session):
    """(evictable checksums, rows behind them, unreadable rooms), deleting none.

    Shares its planning with the sweep so a dry run cannot drift from the run
    it is previewing -- the keep-one-build-per-game rule in particular, which a
    separately written count would miss.
    """
    _, _, unreadable, unreferenced = _plan_datapackage_eviction(session)
    rows = 0
    for start in range(0, len(unreferenced), DATAPACKAGE_MAX_CHECKSUMS_PER_RUN):
        chunk = unreferenced[start:start + DATAPACKAGE_MAX_CHECKSUMS_PER_RUN]
        rows += session.query(DatapackageCache).filter(
            DatapackageCache.checksum.in_(chunk)).count()
    return len(unreferenced), rows, len(unreadable)


def purge_unreferenced_datapackage_cache():
    """Delete cached datapackages that no tracked room references any more.

    datapackage_cache keys on (checksum, entity_type, entity_id): one row per
    item or location name of one apworld build. The checksum identifies that
    build, so every release the community plays brings a full set of rows and
    the previous set stays. Nothing removed them. Both existing deletes in the
    poller exist to force a re-download -- self-healing an incomplete checksum,
    and clearing a checksum immediately before rewriting that same checksum --
    so neither reclaims anything. Meanwhile db_run_cleanup deletes orphaned
    rooms and their history but never the datapackages only those rooms used.
    Production reached 14,997,948 rows and 4.6 GB this way, 40% of the database
    and its second-largest table, growing with the rate the community ships
    apworlds rather than with the user count (#528).

    One build of every game survives even when no room plays it, because three
    routes read this table independently of any room. See
    _plan_datapackage_eviction.

    Evicting the rest is safe, but not free. A missing checksum is a state the
    poller handles: db_get_missing_checksums reports it and the room is queued
    for setup again. That check runs on the supervisor's 15 minute cache sweep,
    though, not on the next poll -- so in between, that room's pushes name
    items as "ID 12345" and the name-based ignore and whitelist filters miss.
    Hence the per-batch re-read below, and the claim run_room_setup now writes
    before it relies on a cached checksum.

    Deleting rows will not shrink the data directory. Postgres returns the pages
    to the table for reuse, so the files hold their high-water mark until a
    VACUUM FULL or pg_repack, which is a locking operation and deliberately not
    attempted here.
    """
    session = Session()
    # Outside the try: a batch that has committed is work done, and the error
    # path has to be able to report it.
    deleted_rows = 0
    deleted_checksums = 0
    try:
        rooms, referenced, unreadable, unreferenced = _plan_datapackage_eviction(session)

        # One unreadable room is not evidence that it needs nothing, but its
        # valid checksums are salvaged in _collect_referenced_checksums, so it
        # cannot lose them. The two guards below are for what is not one bad row.
        refused = {
            'purged_datapackage_checksums': 0,
            'purged_datapackage_rows': 0,
            'datapackage_remaining': False,
            'datapackage_sweep_refused': True,
        }

        if rooms and len(unreadable) > len(rooms) * DATAPACKAGE_UNREADABLE_ABORT_RATIO:
            logging.error(
                "[RETENTION] Refusing the datapackage sweep: %s of %s room(s) "
                "have unreadable game_checksums_json. Sample room ids: %s",
                len(unreadable), len(rooms), unreadable[:20])
            return refused

        if not referenced:
            # Correct answer, cautious action. Nothing referencing anything does
            # mean the whole cache is unreferenced, but it is also what a failed
            # read of tracked_rooms looks like, and the two are indistinguishable
            # from here. A deployment that really has no games yet has nothing
            # worth reclaiming, so waiting for the first room costs it nothing.
            # Not an error: an empty or brand new database is a normal state.
            logging.info(
                "[RETENTION] Skipping the datapackage sweep: no checksum is "
                "referenced by any of %s room(s).", len(rooms))
            return refused

        if unreadable:
            logging.warning(
                "[RETENTION] %s room(s) have unreadable game_checksums_json. "
                "Their valid checksums were salvaged and are protected, but "
                "the rows want fixing: %s",
                len(unreadable), unreadable[:20])

        if not unreferenced:
            return {
                'purged_datapackage_checksums': 0,
                'purged_datapackage_rows': 0,
                'datapackage_remaining': False,
                'datapackage_sweep_refused': False,
            }

        capped = unreferenced[:DATAPACKAGE_MAX_CHECKSUMS_PER_RUN]
        more_remaining = len(unreferenced) > len(capped)

        # Not _purge_in_batches: that batches on model.id, and this table has no
        # id column -- it was dropped in b7f4e2c9a1d3 because its index cost
        # 268 MB and had been scanned twice. Batching on the checksum is also the
        # better unit here, since a checksum is what a re-download restores.
        for start in range(0, len(capped), DATAPACKAGE_CHECKSUM_BATCH_SIZE):
            batch = capped[start:start + DATAPACKAGE_CHECKSUM_BATCH_SIZE]

            # Re-read before every batch. A room set up since the plan was made
            # may have claimed one of these: run_room_setup records its
            # checksums before it looks at the cache, so a claim committed
            # mid-sweep is visible here, and each commit above starts a fresh
            # read-committed snapshot. tracked_rooms is small, so this costs far
            # less than re-downloading an apworld would.
            _, live_referenced, _ = _collect_referenced_checksums(session)
            batch = [checksum for checksum in batch if checksum not in live_referenced]
            if not batch:
                continue

            removed = session.query(DatapackageCache).filter(
                DatapackageCache.checksum.in_(batch)
            ).delete(synchronize_session=False)
            session.commit()
            deleted_rows += removed
            deleted_checksums += len(batch)

        if deleted_checksums:
            logging.info(
                "[RETENTION] Purged %s unreferenced datapackage checksum(s), "
                "%s row(s).%s",
                deleted_checksums, deleted_rows,
                " More remain for the next run." if more_remaining else "",
            )
        return {
            'purged_datapackage_checksums': deleted_checksums,
            'purged_datapackage_rows': deleted_rows,
            'datapackage_remaining': more_remaining,
            'datapackage_sweep_refused': False,
        }
    except Exception as e:
        session.rollback()
        logging.error(
            f"[RETENTION_ERROR] Failed to purge unreferenced datapackages: {e}",
            exc_info=True)
        return {
            # What committed before the failure is real, and reporting zero
            # would have the operator drain read a lock timeout as "nothing
            # left to do". Its own no-progress check stops a loop that cannot
            # get past the same error.
            'purged_datapackage_checksums': deleted_checksums,
            'purged_datapackage_rows': deleted_rows,
            'datapackage_remaining': True,
            'datapackage_sweep_refused': False,
        }
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
        ('stale pending Cheese pushes', purge_stale_cheese_pending_pushes),
        # Last: it reads every room and the whole checksum index, and it is
        # the only step whose work is reclaimable disk rather than
        # correctness, so it yields to the others on a run that fails.
        ('unreferenced datapackages', purge_unreferenced_datapackage_cache),
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
