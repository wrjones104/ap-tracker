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
    UserRoomSubscription, JWTBlocklist,
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
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
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


if __name__ == '__main__':
    unittest.main()
