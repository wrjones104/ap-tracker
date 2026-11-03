"""Retention purge and orphaned-room cleanup.

Covers the two halves of the disk-growth fix:

  * retention_service ages out history in bounded, committed batches, and leaves
    SlotItemCount alone because it is the authority that has to outlive the
    window.
  * db_run_cleanup removes orphaned rooms together with the history that keys on
    them by string with no foreign key, and no longer loses the guest pruning
    when a room delete fails.

The foreign key half is worth stating plainly: before this, every room delete
raised ForeignKeyViolation on slot_item_counts, and because both halves shared a
transaction the rollback discarded the guest pruning too. Neither had ever run in
production.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_retention.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import (
    Base, NotifiedItem, NotifiedHint, SlotItemCount, TrackedRoom, User,
    UserRoomSubscription, JWTBlocklist, DatapackageCache,
)
from app.services import retention_service


class RetentionTestBase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.session = Session()

    def tearDown(self):
        self.session.close()
        Session.remove()
        # Dispose before unlinking, and take the WAL sidecars with the database.
        # Session.remove() only returns the connection to the pool, so the file
        # is still open: on Linux the unlink then succeeds while -wal and -shm
        # stay behind, and the next connection opens a fresh empty database
        # beside a WAL belonging to the old one, which SQLite reads as
        # corruption. Windows refuses the unlink instead, which is why this only
        # ever failed in CI, and only once the file grew enough tests to make
        # the pool open a second connection.
        engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = TEST_DB_PATH + suffix
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _room(self, uuid, last_poll=None):
        room = TrackedRoom(room_id=uuid, tracker_id="t", hostname="archipelago.gg",
                           last_successful_poll=last_poll)
        self.session.add(room)
        self.session.flush()
        return room

    def _items(self, room_uuid, count, age_days, start_index=0):
        for i in range(count):
            self.session.add(NotifiedItem(
                room_id=room_uuid, receiving_slot_id=1, sending_slot_id=2,
                item_id=100 + i, location_id=1000 + start_index + i,
                item_index=start_index + i,
                timestamp=datetime.utcnow() - timedelta(days=age_days),
            ))

    def _hint(self, room_uuid, age_days, location_id):
        self.session.add(NotifiedHint(
            room_id=room_uuid, item_owner_id=1, location_owner_id=2,
            item_id=5, location_id=location_id,
            timestamp=datetime.utcnow() - timedelta(days=age_days),
            updated_at=datetime.utcnow(),
        ))


class TestRetentionPurge(RetentionTestBase):
    def test_purges_past_the_window_and_keeps_the_rest(self):
        self._room("room-a")
        self._items("room-a", 5, age_days=200)
        self._items("room-a", 3, age_days=5, start_index=100)
        self._hint("room-a", age_days=200, location_id=1)
        self._hint("room-a", age_days=5, location_id=2)
        self.session.commit()

        result = retention_service.purge_expired_notification_events(retention_days=90)

        self.assertEqual(result['purged_items'], 5)
        self.assertEqual(result['purged_hints'], 1)
        self.assertFalse(result['events_remaining'])
        self.assertEqual(self.session.query(NotifiedItem).count(), 3)
        self.assertEqual(self.session.query(NotifiedHint).count(), 1)

    def test_leaves_legacy_unindexed_rows_to_the_poller(self):
        """Un-indexed history is the poller's to dispose of, not retention's.

        When a poll meets rows with no item_index it deletes them and resets that
        room's SlotItemCount, so the backfill rebuilds the counts from zero.
        Retention deleting them first skips the reset, and a room revived later
        seeds its counts from the surviving SlotItemCount and increments again.
        With no downward correction left, that doubling is permanent.
        """
        self._room("room-legacy")
        self._items("room-legacy", 3, age_days=200)
        # Same age, but from before the item_index migration.
        for i in range(4):
            self.session.add(NotifiedItem(
                room_id="room-legacy", receiving_slot_id=1, sending_slot_id=2,
                item_id=900 + i, location_id=9000 + i, item_index=None,
                timestamp=datetime.utcnow() - timedelta(days=200),
            ))
        self.session.commit()

        result = retention_service.purge_expired_notification_events(retention_days=90)

        self.assertEqual(result['purged_items'], 3, "indexed rows should still age out")
        surviving = self.session.query(NotifiedItem).filter_by(room_id="room-legacy").all()
        self.assertEqual(len(surviving), 4)
        self.assertTrue(all(r.item_index is None for r in surviving),
                        "retention removed rows the poller has to reset counts for")

    def test_leaves_slot_item_counts_alone(self):
        """The counts are the authority for milestone progress across the window."""
        self._room("room-a")
        self._items("room-a", 4, age_days=200)
        self.session.add(SlotItemCount(room_id="room-a", slot_id=1, item_id=100, count=999))
        self.session.commit()

        retention_service.purge_expired_notification_events(retention_days=90)

        surviving = self.session.query(SlotItemCount).filter_by(room_id="room-a").first()
        self.assertIsNotNone(surviving, "retention deleted the counts it must not touch")
        self.assertEqual(surviving.count, 999)
        self.assertEqual(self.session.query(NotifiedItem).count(), 0)

    def test_batches_across_a_boundary(self):
        """Deleting more rows than one batch holds still clears them all."""
        self._room("room-a")
        self._items("room-a", 25, age_days=200)
        self.session.commit()

        original = retention_service.PURGE_BATCH_SIZE
        retention_service.PURGE_BATCH_SIZE = 10
        try:
            result = retention_service.purge_expired_notification_events(retention_days=90)
        finally:
            retention_service.PURGE_BATCH_SIZE = original

        self.assertEqual(result['purged_items'], 25)
        self.assertEqual(self.session.query(NotifiedItem).count(), 0)

    def test_stops_at_the_per_run_cap_and_reports_more(self):
        self._room("room-a")
        self._items("room-a", 30, age_days=200)
        self.session.commit()

        original_batch = retention_service.PURGE_BATCH_SIZE
        original_cap = retention_service.PURGE_MAX_ROWS_PER_RUN
        retention_service.PURGE_BATCH_SIZE = 5
        retention_service.PURGE_MAX_ROWS_PER_RUN = 10
        try:
            result = retention_service.purge_expired_notification_events(retention_days=90)
        finally:
            retention_service.PURGE_BATCH_SIZE = original_batch
            retention_service.PURGE_MAX_ROWS_PER_RUN = original_cap

        self.assertEqual(result['purged_items'], 10)
        self.assertTrue(result['events_remaining'])
        self.assertEqual(self.session.query(NotifiedItem).count(), 20)

    def test_purges_history_whose_room_is_gone(self):
        self._room("room-live")
        self._items("room-live", 3, age_days=1)
        self._hint("room-live", age_days=1, location_id=1)
        # No TrackedRoom row for this uuid at all.
        self._items("room-dead", 4, age_days=1, start_index=500)
        self._hint("room-dead", age_days=1, location_id=2)
        self.session.commit()

        result = retention_service.purge_orphaned_room_events()

        self.assertEqual(result['purged_orphan_items'], 4)
        self.assertEqual(result['purged_orphan_hints'], 1)
        self.assertEqual(self.session.query(NotifiedItem).count(), 3)
        self.assertEqual(self.session.query(NotifiedHint).count(), 1)

    def test_retention_days_env_override(self):
        os.environ['RETENTION_DAYS'] = '30'
        try:
            self.assertEqual(retention_service.get_retention_days(), 30)
        finally:
            del os.environ['RETENTION_DAYS']

        os.environ['RETENTION_DAYS'] = 'nonsense'
        try:
            self.assertEqual(retention_service.get_retention_days(), 90)
        finally:
            del os.environ['RETENTION_DAYS']

    def test_run_all_continues_past_a_failing_step(self):
        """A step blowing up must not cost the later steps their work.

        The earlier version of this test patched the guest purge to raise and
        asserted the error propagated. That demonstrated ordering, not
        isolation, and it passed against a version of run_all_retention_tasks
        that abandoned everything after the first failure.
        """
        self._room("room-a")
        self._items("room-a", 2, age_days=200)
        self.session.add(JWTBlocklist(jti="expired", expires_at=datetime.utcnow() - timedelta(days=1)))
        self.session.commit()

        original = retention_service.purge_inactive_guest_accounts

        def exploding(*args, **kwargs):
            raise RuntimeError("boom")

        retention_service.purge_inactive_guest_accounts = exploding
        try:
            results = retention_service.run_all_retention_tasks()
        finally:
            retention_service.purge_inactive_guest_accounts = original

        # Ran before the failure.
        self.assertEqual(self.session.query(NotifiedItem).count(), 0)
        # Ran after it. This is the part the old test never reached.
        self.assertEqual(self.session.query(JWTBlocklist).count(), 0)
        self.assertEqual(results.get('purged_jwts'), 1)
        # The failed step contributes nothing rather than a wrong number.
        self.assertNotIn('purged_guests', results)

    def test_guest_purge_has_its_own_window(self):
        """RETENTION_DAYS must not reach account deletion.

        It reads as a history knob, and an operator tightening it to reclaim
        disk must not find it removing guest accounts, and their subscriptions
        and devices through cascades, as a side effect.
        """
        os.environ['RETENTION_DAYS'] = '7'
        try:
            self.assertEqual(retention_service.get_retention_days(), 7)
            self.assertEqual(retention_service.get_guest_inactivity_days(), 90)
        finally:
            del os.environ['RETENTION_DAYS']

        # Its own knob works, and refuses a value low enough to be a mistake.
        os.environ['GUEST_INACTIVITY_DAYS'] = '120'
        try:
            self.assertEqual(retention_service.get_guest_inactivity_days(), 120)
        finally:
            del os.environ['GUEST_INACTIVITY_DAYS']

        os.environ['GUEST_INACTIVITY_DAYS'] = '3'
        try:
            self.assertEqual(retention_service.get_guest_inactivity_days(), 90)
        finally:
            del os.environ['GUEST_INACTIVITY_DAYS']

    def test_janitor_does_not_prune_guests(self):
        """Guest lifetime has one owner.

        db_run_cleanup used to prune guests on a hardcoded 30 day window while
        retention_service did it on a configurable 90 day one. Because the
        janitor runs the former first, guests went 60 days earlier than every
        doc promised and RETENTION_DAYS had no effect on them.
        """
        from app.poller import db_run_cleanup

        long_ago = datetime.utcnow() - timedelta(days=45)
        stale = User(guest_uuid="g-45-days", is_guest=True, last_activity=long_ago)
        self.session.add(stale)
        self.session.commit()

        db_run_cleanup()
        self.session.expire_all()

        survivors = {u.guest_uuid for u in self.session.query(User).all()}
        self.assertIn("g-45-days", survivors,
                      "the janitor pruned a guest inside the 90 day window")


class TestJanitorRoomCleanup(RetentionTestBase):
    def test_removes_orphaned_rooms_with_their_history(self):
        from app.poller import db_run_cleanup

        long_ago = datetime.utcnow() - timedelta(days=60)
        orphan = self._room("room-orphan", last_poll=long_ago)
        keeper = self._room("room-keeper", last_poll=long_ago)

        user = User(discord_id="1", discord_username="u")
        self.session.add(user)
        self.session.flush()
        self.session.add(UserRoomSubscription(user_id=user.id, room_id=keeper.id, alias="Keep"))

        self._items("room-orphan", 4, age_days=1)
        self._hint("room-orphan", age_days=1, location_id=1)
        self.session.add(SlotItemCount(room_id="room-orphan", slot_id=1, item_id=100, count=7))

        self._items("room-keeper", 2, age_days=1, start_index=900)
        self.session.add(SlotItemCount(room_id="room-keeper", slot_id=1, item_id=100, count=3))
        self.session.commit()

        db_run_cleanup()
        self.session.expire_all()

        rooms = {r.room_id for r in self.session.query(TrackedRoom).all()}
        self.assertEqual(rooms, {"room-keeper"}, "orphaned room was not collected")

        # Its history keys on the uuid string with no foreign key, so the janitor
        # has to remove it explicitly or it survives unreachable forever.
        self.assertEqual(
            self.session.query(NotifiedItem).filter_by(room_id="room-orphan").count(), 0
        )
        self.assertEqual(
            self.session.query(NotifiedHint).filter_by(room_id="room-orphan").count(), 0
        )
        # slot_item_counts goes with it via ON DELETE CASCADE.
        self.assertEqual(
            self.session.query(SlotItemCount).filter_by(room_id="room-orphan").count(), 0
        )

        # The subscribed room is untouched.
        self.assertEqual(
            self.session.query(NotifiedItem).filter_by(room_id="room-keeper").count(), 2
        )
        self.assertEqual(
            self.session.query(SlotItemCount).filter_by(room_id="room-keeper").count(), 1
        )

    def test_guest_purge_is_retentions_job_and_spares_the_rest(self):
        """Room deletion and guest removal are separate concerns now.

        db_run_cleanup deletes the orphaned room without touching any account;
        purge_inactive_guest_accounts owns guest lifetime, on its own window, and
        never touches a Discord account.
        """
        from app.poller import db_run_cleanup

        long_ago = datetime.utcnow() - timedelta(days=200)
        self._room("room-orphan", last_poll=long_ago)
        self.session.add(SlotItemCount(room_id="room-orphan", slot_id=1, item_id=100, count=7))

        stale = User(guest_uuid="g-stale", is_guest=True, last_activity=long_ago)
        fresh = User(guest_uuid="g-fresh", is_guest=True, last_activity=datetime.utcnow())
        member = User(discord_id="42", discord_username="real", is_guest=False, last_activity=long_ago)
        self.session.add_all([stale, fresh, member])
        self.session.commit()

        db_run_cleanup()
        self.session.expire_all()

        # The room goes, which is the foreign key fix working.
        self.assertEqual(self.session.query(TrackedRoom).count(), 0)
        self.assertEqual(
            self.session.query(SlotItemCount).filter_by(room_id="room-orphan").count(), 0
        )
        # No account is touched by the janitor.
        self.assertEqual(self.session.query(User).count(), 3)

        retention_service.purge_inactive_guest_accounts()
        self.session.expire_all()

        remaining = {u.guest_uuid or u.discord_id for u in self.session.query(User).all()}
        self.assertNotIn("g-stale", remaining, "stale guest survived the retention purge")
        self.assertIn("g-fresh", remaining)
        self.assertIn("42", remaining, "a Discord account was pruned")


class TestDatapackageCacheSweep(RetentionTestBase):
    """The sweep that reclaims cached apworld builds no room references (#528).

    Nothing had ever deleted these. A checksum is one apworld build, and both
    existing deletes in the poller are re-download triggers rather than
    eviction, so production reached 15M rows across versions nobody plays.
    """

    def _room_with_games(self, uuid, checksums_json):
        room = TrackedRoom(room_id=uuid, tracker_id="t", hostname="archipelago.gg",
                           game_checksums_json=checksums_json)
        self.session.add(room)
        self.session.flush()
        return room

    def _cache(self, checksum, rows=3, game="AGame", marker=None):
        """Cache `rows` item names, plus the _metadata marker when asked.

        The marker is the row db_get_missing_checksums reads to decide a
        checksum is cached at all, and the sweep prefers a _completed_v2 build
        when it keeps one. It counts as a row like any other.
        """
        for i in range(rows):
            self.session.add(DatapackageCache(
                game=game, checksum=checksum, entity_type="item",
                entity_id=i, entity_name=f"{game}-item-{i}",
            ))
        if marker:
            self.session.add(DatapackageCache(
                game=game, checksum=checksum, entity_type="_metadata",
                entity_id=0, entity_name=marker,
            ))

    def test_evicts_only_what_no_room_references(self):
        self._room_with_games("room-a", '{"AGame": "live-1"}')
        self._room_with_games("room-b", '{"BGame": "live-2"}')
        self._cache("live-1", rows=3)
        self._cache("live-2", rows=2)
        self._cache("dead-1", rows=4)
        self._cache("dead-2", rows=5)
        self.session.commit()

        result = retention_service.purge_unreferenced_datapackage_cache()

        self.assertEqual(result['purged_datapackage_checksums'], 2)
        self.assertEqual(result['purged_datapackage_rows'], 9)
        self.assertFalse(result['datapackage_remaining'])
        self.assertFalse(result['datapackage_sweep_refused'])

        surviving = {c for (c,) in self.session.query(DatapackageCache.checksum).distinct()}
        self.assertEqual(surviving, {"live-1", "live-2"})

    def test_a_suspended_or_complete_room_still_protects_its_checksum(self):
        """Those rooms are not polled, but they are not gone either."""
        room = self._room_with_games("room-idle", '{"AGame": "idle-1"}')
        room.is_suspended = True
        room.is_complete = True
        self._cache("idle-1", rows=2)
        self.session.commit()

        result = retention_service.purge_unreferenced_datapackage_cache()

        self.assertEqual(result['purged_datapackage_checksums'], 0)
        self.assertEqual(self.session.query(DatapackageCache).count(), 2)

    def test_one_unreadable_room_does_not_stop_the_sweep(self):
        """A single corrupt row must not stall the sweep for good.

        It is left out of the reference set, which risks evicting a checksum
        only that room needed. The cost of being wrong is one re-download, and
        the alternative is a sweep that never runs again and says nothing.
        """
        for i in range(19):
            self._room_with_games(f"room-{i}", '{"AGame": "live-1"}')
        self._room_with_games("room-broken", 'not json at all')
        self._cache("live-1", rows=2)
        self._cache("dead-1", rows=2)
        self.session.commit()

        with self.assertLogs(level='WARNING') as logs:
            result = retention_service.purge_unreferenced_datapackage_cache()

        self.assertEqual(result['purged_datapackage_checksums'], 1)
        self.assertFalse(result['datapackage_sweep_refused'])
        self.assertTrue(any("unreadable game_checksums_json" in line for line in logs.output))

    def test_refuses_when_too_many_rooms_are_unreadable(self):
        """Mass corruption would otherwise read as 'evict everything'."""
        for i in range(8):
            self._room_with_games(f"room-{i}", '{"AGame": "live-1"}')
        for i in range(2):
            self._room_with_games(f"room-bad-{i}", '[]')
        self._cache("live-1", rows=2)
        self._cache("dead-1", rows=2)
        self.session.commit()

        with self.assertLogs(level='ERROR') as logs:
            result = retention_service.purge_unreferenced_datapackage_cache()

        self.assertTrue(result['datapackage_sweep_refused'])
        self.assertEqual(result['purged_datapackage_checksums'], 0)
        self.assertEqual(self.session.query(DatapackageCache).count(), 4)
        self.assertTrue(any("Refusing the datapackage sweep" in line for line in logs.output))

    def test_refuses_when_nothing_is_referenced_at_all(self):
        """Also what a failed read of tracked_rooms looks like, so it waits."""
        self._room_with_games("room-empty", '{}')
        self._cache("dead-1", rows=3)
        self.session.commit()

        result = retention_service.purge_unreferenced_datapackage_cache()

        self.assertTrue(result['datapackage_sweep_refused'])
        self.assertEqual(self.session.query(DatapackageCache).count(), 3)

    def test_stops_at_the_per_run_cap_and_reports_more(self):
        self._room_with_games("room-a", '{"AGame": "live-1"}')
        self._cache("live-1", rows=1)
        for i in range(5):
            self._cache(f"dead-{i}", rows=2)
        self.session.commit()

        original_cap = retention_service.DATAPACKAGE_MAX_CHECKSUMS_PER_RUN
        original_batch = retention_service.DATAPACKAGE_CHECKSUM_BATCH_SIZE
        retention_service.DATAPACKAGE_MAX_CHECKSUMS_PER_RUN = 3
        retention_service.DATAPACKAGE_CHECKSUM_BATCH_SIZE = 2
        try:
            first = retention_service.purge_unreferenced_datapackage_cache()
            second = retention_service.purge_unreferenced_datapackage_cache()
        finally:
            retention_service.DATAPACKAGE_MAX_CHECKSUMS_PER_RUN = original_cap
            retention_service.DATAPACKAGE_CHECKSUM_BATCH_SIZE = original_batch

        self.assertEqual(first['purged_datapackage_checksums'], 3)
        self.assertTrue(first['datapackage_remaining'])
        self.assertEqual(second['purged_datapackage_checksums'], 2)
        self.assertFalse(second['datapackage_remaining'])
        # The referenced one is still there after both runs.
        surviving = {c for (c,) in self.session.query(DatapackageCache.checksum).distinct()}
        self.assertEqual(surviving, {"live-1"})

    def test_run_all_includes_the_sweep(self):
        self._room_with_games("room-a", '{"AGame": "live-1"}')
        self._cache("live-1", rows=1)
        self._cache("dead-1", rows=2)
        self.session.commit()

        results = retention_service.run_all_retention_tasks()

        self.assertEqual(results.get('purged_datapackage_checksums'), 1)
        self.assertEqual(results.get('purged_datapackage_rows'), 2)


    def test_keeps_one_build_of_a_game_no_room_plays(self):
        """GET /games is this table, so a game must not lose its last build.

        /games and /games/<game>/items are served from datapackage_cache alone,
        and the milestone, ignore-list and whitelist editors read them for
        games the user has never tracked. The iOS guide calls /games "every
        game name the server knows", and that client cannot be updated.
        """
        self._room_with_games("room-a", '{"AGame": "live-1"}')
        self._cache("live-1", rows=2, game="AGame")
        self._cache("idle-old", rows=2, game="IdleGame")
        self._cache("idle-new", rows=2, game="IdleGame", marker="_completed_v2")
        self._cache("idle-mid", rows=2, game="IdleGame", marker="_empty_datapackage")
        self.session.commit()

        result = retention_service.purge_unreferenced_datapackage_cache()

        surviving = {c for (c,) in self.session.query(DatapackageCache.checksum).distinct()}
        # The complete build is the one worth keeping, and choosing it the same
        # way every time is what makes a repeated drain converge.
        self.assertEqual(surviving, {"live-1", "idle-new"})
        self.assertEqual(result['purged_datapackage_checksums'], 2)

    def test_an_older_build_of_a_game_in_play_is_still_evicted(self):
        """Keeping a fallback is per game, not per build."""
        self._room_with_games("room-a", '{"AGame": "live-1"}')
        self._cache("live-1", rows=2, game="AGame", marker="_completed_v2")
        self._cache("stale-1", rows=4, game="AGame", marker="_completed_v2")
        self._cache("stale-2", rows=4, game="AGame")
        self.session.commit()

        result = retention_service.purge_unreferenced_datapackage_cache()

        surviving = {c for (c,) in self.session.query(DatapackageCache.checksum).distinct()}
        self.assertEqual(surviving, {"live-1"})
        self.assertEqual(result['purged_datapackage_checksums'], 2)

    def test_salvages_the_valid_checksums_of_a_partly_broken_room(self):
        """A null in the map must not cost that room its other datapackages.

        room_checksums rejects the whole map, by design, so one bad entry
        cannot trap the room in the setup retry loop. The consequence here is
        that nothing would ever re-download what the sweep took: every repair
        path reads the same column and skips the room, so it polls on forever
        against names it cannot resolve.
        """
        for i in range(19):
            self._room_with_games(f"room-{i}", '{"AGame": "live-1"}')
        self._room_with_games("room-partial", '{"BGame": "live-2", "CGame": null}')
        self._cache("live-1", rows=2, game="AGame")
        self._cache("live-2", rows=2, game="BGame")
        self._cache("dead-1", rows=2, game="AGame")
        self.session.commit()

        with self.assertLogs(level='WARNING') as logs:
            result = retention_service.purge_unreferenced_datapackage_cache()

        surviving = {c for (c,) in self.session.query(DatapackageCache.checksum).distinct()}
        self.assertIn("live-2", surviving, "salvageable checksum was evicted")
        self.assertNotIn("dead-1", surviving)
        self.assertFalse(result['datapackage_sweep_refused'])
        self.assertTrue(any("unreadable game_checksums_json" in line for line in logs.output))

    def test_the_unreadable_ratio_is_a_boundary_not_a_range(self):
        """10% of 20 rooms is 2: two proceeds, three refuses."""
        def build(bad):
            self.session.query(TrackedRoom).delete()
            self.session.query(DatapackageCache).delete()
            for i in range(20 - bad):
                self._room_with_games(f"room-{i}", '{"AGame": "live-1"}')
            for i in range(bad):
                self._room_with_games(f"room-bad-{i}", '[]')
            self._cache("live-1", rows=1, game="AGame")
            self._cache("dead-1", rows=1, game="AGame")
            self.session.commit()

        build(2)
        self.assertFalse(
            retention_service.purge_unreferenced_datapackage_cache()['datapackage_sweep_refused'],
            "exactly 10% unreadable should not refuse")

        build(3)
        with self.assertLogs(level='ERROR'):
            self.assertTrue(
                retention_service.purge_unreferenced_datapackage_cache()['datapackage_sweep_refused'],
                "above 10% unreadable should refuse")

    def test_a_room_that_claims_a_checksum_mid_sweep_keeps_it(self):
        """run_room_setup records its checksums before it reads the cache.

        The sweep plans against one snapshot and then deletes over several
        transactions, so a setup finishing in between would otherwise lose the
        datapackage it had just decided it did not need to download.
        """
        self._room_with_games("room-a", '{"AGame": "live-1"}')
        self._cache("live-1", rows=1, game="AGame")
        for name in ("dead-1", "dead-2", "dead-3", "dead-4"):
            self._cache(name, rows=1, game="AGame")
        self.session.commit()

        original = retention_service._collect_referenced_checksums
        calls = []

        def claiming(session):
            calls.append(1)
            # Between the plan and the first delete batch, a setup commits.
            if len(calls) == 2:
                session.add(TrackedRoom(room_id="room-late", tracker_id="t",
                                        hostname="archipelago.gg",
                                        game_checksums_json='{"AGame": "dead-3"}'))
                session.commit()
            return original(session)

        retention_service._collect_referenced_checksums = claiming
        retention_service.DATAPACKAGE_CHECKSUM_BATCH_SIZE = 1
        try:
            retention_service.purge_unreferenced_datapackage_cache()
        finally:
            retention_service._collect_referenced_checksums = original
            retention_service.DATAPACKAGE_CHECKSUM_BATCH_SIZE = 25

        surviving = {c for (c,) in self.session.query(DatapackageCache.checksum).distinct()}
        self.assertIn("dead-3", surviving, "a checksum claimed mid-sweep was evicted")
        self.assertIn("live-1", surviving)

    def test_a_batch_that_blows_up_still_reports_what_committed(self):
        """Reporting zero would read as "nothing left" and stop the drain."""
        self._room_with_games("room-a", '{"AGame": "live-1"}')
        self._cache("live-1", rows=1, game="AGame")
        for name in ("dead-1", "dead-2", "dead-3", "dead-4"):
            self._cache(name, rows=2, game="AGame")
        self.session.commit()

        original = retention_service._collect_referenced_checksums
        calls = []

        def exploding(session):
            calls.append(1)
            # Plan, batch 1, then the re-read for batch 2 fails.
            if len(calls) == 3:
                raise RuntimeError("lock timeout")
            return original(session)

        retention_service._collect_referenced_checksums = exploding
        retention_service.DATAPACKAGE_CHECKSUM_BATCH_SIZE = 1
        try:
            with self.assertLogs(level='ERROR'):
                result = retention_service.purge_unreferenced_datapackage_cache()
        finally:
            retention_service._collect_referenced_checksums = original
            retention_service.DATAPACKAGE_CHECKSUM_BATCH_SIZE = 25

        self.assertEqual(result['purged_datapackage_checksums'], 1)
        self.assertEqual(result['purged_datapackage_rows'], 2)
        self.assertTrue(result['datapackage_remaining'],
                        "an interrupted run still has work left")

    def test_the_survey_reports_what_the_sweep_would_do(self):
        """The dry run previews the real run, keep-one-build rule included."""
        self._room_with_games("room-a", '{"AGame": "live-1"}')
        self._cache("live-1", rows=2, game="AGame")
        self._cache("dead-1", rows=3, game="AGame")
        self._cache("idle-1", rows=4, game="IdleGame")
        self.session.commit()

        checksums, rows, unreadable = (
            retention_service.survey_unreferenced_datapackage_cache(self.session))
        self.assertEqual((checksums, rows, unreadable), (1, 3, 0))

        result = retention_service.purge_unreferenced_datapackage_cache()
        self.assertEqual(result['purged_datapackage_checksums'], checksums)
        self.assertEqual(result['purged_datapackage_rows'], rows)

if __name__ == '__main__':
    unittest.main()
