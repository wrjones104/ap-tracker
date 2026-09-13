"""One undeletable row costs one row, not the whole run.

#331 is the shape this guards against: a guest owned a milestone template,
milestone_templates had no cascade, and the delete raised. Because the purge put
every guest in one transaction behind one commit, that single row discarded
every other guest in the run -- and because the selection is deterministic, the
same row failed again on every run after it. The cleanup was dead until someone
read the logs.

That specific cascade is fixed and every foreign key referencing users.id now
carries ON DELETE CASCADE, so there is no live trigger. These tests pin the
structural property instead: whatever the next un-cascaded relationship turns
out to be, it must cost its own row and nothing else.

The blocker here is a real table with a real foreign key and no cascade, created
through the same SQLite connection the app uses, rather than a patched session.
A mocked delete would prove the except block runs; it would not prove the
surrounding transaction survives a genuine IntegrityError, which is the part
that failed in #331.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_janitor_isolation.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text

from app import create_app, Session, engine
from app.models import Base, TrackedRoom, User
from app.poller import db_run_cleanup
from app.services import retention_service


class JanitorIsolationTestBase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.session = Session()

    def tearDown(self):
        self.session.close()
        Session.remove()
        # Before unlinking, so the pool cannot go on serving an unlinked inode.
        engine.dispose()
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def _block_user_deletes(self):
        """A referencing table with no cascade: exactly #331's situation."""
        self.session.execute(text(
            "CREATE TABLE IF NOT EXISTS undeletable_user_ref ("
            "  id INTEGER PRIMARY KEY,"
            "  user_id INTEGER REFERENCES users(id)"
            ")"
        ))

    def _block_room_deletes(self):
        self.session.execute(text(
            "CREATE TABLE IF NOT EXISTS undeletable_room_ref ("
            "  id INTEGER PRIMARY KEY,"
            "  room_id INTEGER REFERENCES tracked_rooms(id)"
            ")"
        ))

    def _pin_user(self, user):
        self.session.execute(
            text("INSERT INTO undeletable_user_ref (user_id) VALUES (:uid)"),
            {"uid": user.id},
        )

    def _pin_room(self, room):
        self.session.execute(
            text("INSERT INTO undeletable_room_ref (room_id) VALUES (:rid)"),
            {"rid": room.id},
        )

    def _guest(self, uuid, days_idle):
        user = User(
            guest_uuid=uuid, is_guest=True,
            last_activity=datetime.utcnow() - timedelta(days=days_idle),
        )
        self.session.add(user)
        self.session.flush()
        return user

    def _orphan_room(self, uuid, days_since_poll=200):
        room = TrackedRoom(
            room_id=uuid, tracker_id="t", hostname="archipelago.gg",
            last_successful_poll=datetime.utcnow() - timedelta(days=days_since_poll),
        )
        self.session.add(room)
        self.session.flush()
        return room

    def _guest_uuids(self):
        self.session.expire_all()
        return {u.guest_uuid for u in self.session.query(User).all()}

    def _room_uuids(self):
        self.session.expire_all()
        return {r.room_id for r in self.session.query(TrackedRoom).all()}


class TestGuestPurgeIsolation(JanitorIsolationTestBase):
    def test_one_undeletable_guest_does_not_save_the_others(self):
        """The #331 mechanism, on the path that owns guest retention today."""
        self._block_user_deletes()
        stuck = self._guest("g-stuck", days_idle=200)
        self._guest("g-a", days_idle=200)
        self._guest("g-b", days_idle=200)
        self._pin_user(stuck)
        self.session.commit()

        result = retention_service.purge_inactive_guest_accounts()

        remaining = self._guest_uuids()
        self.assertIn("g-stuck", remaining, "the blocked guest should survive")
        self.assertNotIn("g-a", remaining, "a deletable guest was rolled back with it")
        self.assertNotIn("g-b", remaining, "a deletable guest was rolled back with it")
        self.assertEqual(result.get('purged_guests'), 2)

    def test_the_skip_is_reported_not_silent(self):
        """A recurring failure has to be visible as a number."""
        self._block_user_deletes()
        stuck = self._guest("g-stuck", days_idle=200)
        self._guest("g-a", days_idle=200)
        self._pin_user(stuck)
        self.session.commit()

        result = retention_service.purge_inactive_guest_accounts()

        self.assertEqual(result.get('skipped_guests'), 1)

    def test_a_later_run_still_makes_progress(self):
        """Deterministic selection is what made #331 permanent: the same row
        failed every time and took the run with it."""
        self._block_user_deletes()
        stuck = self._guest("g-stuck", days_idle=200)
        self._guest("g-a", days_idle=200)
        self._pin_user(stuck)
        self.session.commit()

        retention_service.purge_inactive_guest_accounts()
        self._guest("g-c", days_idle=200)
        self.session.commit()

        retention_service.purge_inactive_guest_accounts()

        remaining = self._guest_uuids()
        self.assertEqual(remaining, {"g-stuck"}, "a later run was still blocked")

    def test_clean_run_is_unchanged(self):
        """No blocker: every stale guest goes, fresh ones stay, and nothing is
        reported as skipped."""
        self._guest("g-stale", days_idle=200)
        self._guest("g-fresh", days_idle=1)
        self.session.commit()

        result = retention_service.purge_inactive_guest_accounts()

        self.assertEqual(self._guest_uuids(), {"g-fresh"})
        self.assertEqual(result.get('purged_guests'), 1)
        self.assertEqual(result.get('skipped_guests', 0), 0)

    def test_purge_commits_in_batches(self):
        """The siblings in this module are all bounded; this one was not.

        Run with a batch size of 2 across 5 guests, so completion cannot come
        from a single final commit.
        """
        original = retention_service.GUEST_PURGE_BATCH_SIZE
        retention_service.GUEST_PURGE_BATCH_SIZE = 2
        try:
            for i in range(5):
                self._guest(f"g-{i}", days_idle=200)
            self.session.commit()

            result = retention_service.purge_inactive_guest_accounts()
        finally:
            retention_service.GUEST_PURGE_BATCH_SIZE = original

        self.assertEqual(self._guest_uuids(), set())
        self.assertEqual(result.get('purged_guests'), 5)


class TestRoomCleanupIsolation(JanitorIsolationTestBase):
    def test_one_undeletable_room_does_not_stop_the_rest(self):
        """db_run_cleanup deletes in chunks, and the guard used to sit outside
        the chunk loop, so a failing chunk skipped every chunk after it."""
        self._block_room_deletes()
        stuck = self._orphan_room("r-stuck")
        self._orphan_room("r-a")
        self._orphan_room("r-b")
        self._pin_room(stuck)
        self.session.commit()

        db_run_cleanup()

        remaining = self._room_uuids()
        self.assertIn("r-stuck", remaining, "the blocked room should survive")
        self.assertNotIn("r-a", remaining, "a deletable room was lost to the bad one")
        self.assertNotIn("r-b", remaining, "a deletable room was lost to the bad one")

    def test_a_later_run_still_collects_new_orphans(self):
        self._block_room_deletes()
        stuck = self._orphan_room("r-stuck")
        self._pin_room(stuck)
        self.session.commit()

        db_run_cleanup()

        self._orphan_room("r-new")
        self.session.commit()

        db_run_cleanup()

        self.assertEqual(self._room_uuids(), {"r-stuck"}, "a later run was still blocked")

    def test_clean_run_is_unchanged(self):
        self._orphan_room("r-old")
        self._orphan_room("r-recent", days_since_poll=1)
        self.session.commit()

        db_run_cleanup()

        self.assertEqual(self._room_uuids(), {"r-recent"})


if __name__ == '__main__':
    unittest.main()
