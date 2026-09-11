"""One-off drain of the retention backlog.

The janitor in poller.py caps each table at PURGE_MAX_ROWS_PER_RUN per 24 hour
run, which is far above the rate history accumulates but far below the years of
backlog sitting there the first time retention is switched on. At the default
cap a four million row backlog takes about three weeks to clear.

This runs the same retention functions in a loop until they report nothing left,
so the backlog is a supervised operation in a window you choose rather than
something the poller grinds through unattended. It shares the batching, so the
poller is never locked out for long, and it is interruptible: every batch is
committed, so stopping it loses nothing and re-running resumes.

Run it before pg_repack. Deletes alone do not return space to the operating
system, they only make it reusable.

    python backend/purge_backlog.py --dry-run
    python backend/purge_backlog.py --batch-size 2000
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from sqlalchemy import text, exists
    from app import Session
    from app.models import NotifiedItem, NotifiedHint, TrackedRoom, User, SlotItemCount
    from app.services import retention_service
except ImportError as e:
    print("Error: Could not import app modules. Please run this script from the repository root.")
    print(f"Details: {e}")
    sys.exit(1)


# Sizes come from the catalog; row counts are counted for real. n_live_tup is an
# autovacuum estimate, so straight after a large delete it still reports the
# pre-purge figure and makes the run look like it did nothing.
SIZE_QUERY = text("""
    SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) AS total
    FROM pg_stat_user_tables
    WHERE relname IN ('notified_items','notified_hints','slot_item_counts','tracked_rooms')
    ORDER BY pg_total_relation_size(relid) DESC
""")

COUNTED_TABLES = {
    'notified_items': NotifiedItem,
    'notified_hints': NotifiedHint,
    'slot_item_counts': SlotItemCount,
    'tracked_rooms': TrackedRoom,
}


def is_postgres(session):
    return session.bind.dialect.name == 'postgresql'


def show_sizes(session, label):
    if not is_postgres(session):
        return
    print(f"\n{label}")
    print(f"  {'table':<20} {'total':>12} {'rows':>14}")
    for relname, total in session.execute(SIZE_QUERY):
        model = COUNTED_TABLES.get(relname)
        rows = session.query(model).count() if model is not None else 0
        print(f"  {relname:<20} {total:>12} {rows:>14,}")
    print("  (total size does not fall until the table is repacked)")


def survey(session, retention_days):
    """What the purge would remove, without removing it."""
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    counts = {
        'items past the window': session.query(NotifiedItem).filter(
            NotifiedItem.timestamp < cutoff).count(),
        'hints past the window': session.query(NotifiedHint).filter(
            NotifiedHint.timestamp < cutoff).count(),
        'items with no room': session.query(NotifiedItem).filter(
            ~exists().where(TrackedRoom.room_id == NotifiedItem.room_id)).count(),
        'hints with no room': session.query(NotifiedHint).filter(
            ~exists().where(TrackedRoom.room_id == NotifiedHint.room_id)).count(),
        'rooms with no subscribers': session.query(TrackedRoom).filter(
            TrackedRoom.subscriptions.any() == False,
            (TrackedRoom.last_successful_poll == None) |
            (TrackedRoom.last_successful_poll < thirty_days_ago)
        ).count(),
    }
    return counts


def drain(step_name, fn, remaining_key, total_keys, pause):
    """Call a capped retention function until it reports nothing remaining."""
    totals = {k: 0 for k in total_keys}
    passes = 0
    started = time.time()

    while True:
        result = fn()
        passes += 1
        for k in total_keys:
            totals[k] += result.get(k, 0)

        moved = sum(result.get(k, 0) for k in total_keys)
        print(f"  pass {passes:>3}: {moved:>8,} rows   "
              f"(running total {sum(totals.values()):,})", flush=True)

        if not result.get(remaining_key):
            break
        if moved == 0:
            # Reported more remaining but removed nothing. Stop rather than spin.
            print("  stopping: no progress on the last pass")
            break
        if pause:
            time.sleep(pause)

    elapsed = time.time() - started
    print(f"  {step_name}: {sum(totals.values()):,} rows in {passes} passes, {elapsed:.1f}s")
    return totals


def main():
    parser = argparse.ArgumentParser(description="Drain the retention backlog in bounded batches.")
    parser.add_argument('--dry-run', action='store_true',
                        help="Report what would be removed and exit.")
    parser.add_argument('--batch-size', type=int, default=None,
                        help=f"Rows per transaction (default {retention_service.PURGE_BATCH_SIZE}).")
    parser.add_argument('--retention-days', type=int, default=None,
                        help="Override the retention window for this run.")
    parser.add_argument('--pause', type=float, default=0.0,
                        help="Seconds to sleep between passes, to be gentler on the poller.")
    parser.add_argument('--skip-rooms', action='store_true',
                        help="Do not remove orphaned rooms, only history.")
    args = parser.parse_args()

    retention_days = args.retention_days or retention_service.get_retention_days()
    if args.batch_size:
        retention_service.PURGE_BATCH_SIZE = args.batch_size

    print("=" * 78)
    print("             AP Tracker - Retention Backlog Drain")
    print("=" * 78)
    print(f"Retention window: {retention_days} days")
    print(f"Batch size:       {retention_service.PURGE_BATCH_SIZE:,} rows per transaction")

    session = Session()
    try:
        show_sizes(session, "Before:")
        print("\nPending work:")
        for label, n in survey(session, retention_days).items():
            print(f"  {label:<28} {n:>12,}")
    finally:
        Session.remove()

    if args.dry_run:
        print("\nDry run, nothing removed.")
        return

    print("\nStarting. Every batch commits, so interrupting is safe and re-running resumes.\n")

    print("1. History whose room no longer exists")
    drain("orphaned history", retention_service.purge_orphaned_room_events,
          'orphans_remaining', ['purged_orphan_items', 'purged_orphan_hints'], args.pause)

    print("\n2. History past the retention window")
    drain("aged history",
          lambda: retention_service.purge_expired_notification_events(retention_days=retention_days),
          'events_remaining', ['purged_items', 'purged_hints'], args.pause)

    if not args.skip_rooms:
        print("\n3. Orphaned rooms, their history and their counts")
        from app.poller import db_run_cleanup
        db_run_cleanup()
        print("  done (see the JANITOR log lines above for totals)")

    print("\n4. Inactive guests and expired blocklist entries")
    guests = retention_service.purge_inactive_guest_accounts(inactivity_days=retention_days)
    jwts = retention_service.purge_expired_jwt_blocklist()
    print(f"  guests: {guests.get('purged_guests', 0):,}   "
          f"blocklist: {jwts.get('purged_jwts', 0):,}")

    session = Session()
    try:
        show_sizes(session, "\nAfter:")
    finally:
        Session.remove()

    print("""
Space is now reusable but has not been returned to the operating system.
To actually shrink the files, repack the largest tables, biggest first:

    pg_repack -d <database> -t notified_items
    pg_repack -d <database> -t notified_hints
    pg_repack -d <database> -t datapackage_cache

Each one needs free disk roughly equal to the live size of the table it is
rebuilding, so check df first.
""")


if __name__ == '__main__':
    main()
