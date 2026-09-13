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

from unittest import mock

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as OrmSession

from app import create_app, Session, engine
import app.poller as poller
from app.models import Base, NotifiedHint, NotifiedItem, TrackedRoom, User
from app.poller import db_run_cleanup
from app.services import retention_service


def _outage(*args, **kwargs):
    raise OperationalError("DELETE ...", {}, Exception("server closed the connection"))


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

    def _history(self, room_uuid):
        self.session.add(NotifiedItem(
            room_id=room_uuid, receiving_slot_id=1, sending_slot_id=2,
            item_id=100, location_id=1000, item_index=0,
            timestamp=datetime.utcnow(),
        ))
        self.session.add(NotifiedHint(
            room_id=room_uuid, item_owner_id=1, location_owner_id=2,
            item_id=5, location_id=1, timestamp=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        ))

    def _history_rooms(self):
        self.session.expire_all()
        return (
            {r for (r,) in self.session.query(NotifiedItem.room_id).all()},
            {r for (r,) in self.session.query(NotifiedHint.room_id).all()},
        )

    def _commit_then(self, after_first):
        """Patch Session.commit to count calls and run `after_first` once,
        straight after the first real commit.

        This is how the tests stand in for a concurrent request: it lands
        between two of the purge's batches, on its own connection, which is
        exactly the window multi-commit batching opened.
        """
        commits = []
        real_commit = OrmSession.commit

        def counting_commit(s):
            result = real_commit(s)
            commits.append(1)
            if len(commits) == 1 and after_first:
                with engine.begin() as conn:
                    after_first(conn)
            return result

        return commits, mock.patch.object(OrmSession, "commit", counting_commit)

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
        """5 guests at batch size 2 must commit exactly three times: 2, 2, 1.

        Counted directly, because the end state cannot show it on SQLite. With
        pysqlite's default transaction handling a SELECT does not open a
        transaction, so each SAVEPOINT becomes the outermost one and its RELEASE
        commits the guest by itself. The guests disappear even if the purge
        never commits, which is how an earlier version of this test passed with
        commit patched out entirely. Postgres would roll the last partial batch
        back instead.
        """
        for i in range(5):
            self._guest(f"g-{i}", days_idle=200)
        self.session.commit()

        commits, patched = self._commit_then(None)
        with mock.patch.object(retention_service, "GUEST_PURGE_BATCH_SIZE", 2), patched:
            result = retention_service.purge_inactive_guest_accounts()

        self.assertEqual(len(commits), 3, "batches did not commit as 2 + 2 + final 1")
        self.assertEqual(self._guest_uuids(), set())
        self.assertEqual(result.get('purged_guests'), 5)

    def test_guest_who_upgrades_mid_run_is_not_deleted(self):
        """The data-loss race multi-commit batching opened.

        The id list is read once. A guest queued for a later batch who links a
        Discord account in the meantime is now a registered user, and deleting
        them would cascade away a live account and everything it owns.
        """
        self._guest("g-first", days_idle=200)
        upgrader = self._guest("g-upgrades", days_idle=200)
        self.session.commit()
        upgrader_id = upgrader.id

        def upgrade(conn):
            conn.execute(
                text("UPDATE users SET is_guest = 0, discord_id = '99' WHERE id = :id"),
                {"id": upgrader_id},
            )

        commits, patched = self._commit_then(upgrade)
        with mock.patch.object(retention_service, "GUEST_PURGE_BATCH_SIZE", 1), patched:
            result = retention_service.purge_inactive_guest_accounts()

        self.session.expire_all()
        self.assertIsNotNone(
            self.session.get(User, upgrader_id),
            "an account that upgraded mid-run was deleted from a stale id list")
        self.assertEqual(result.get('purged_guests'), 1)

    def test_guest_who_comes_back_mid_run_is_not_deleted(self):
        """Every authenticated request stamps last_activity. A guest who opens
        the app while the run is working through the list is not inactive."""
        self._guest("g-first", days_idle=200)
        returner = self._guest("g-returns", days_idle=200)
        self.session.commit()
        returner_id = returner.id

        def come_back(conn):
            conn.execute(
                text("UPDATE users SET last_activity = :now WHERE id = :id"),
                {"now": datetime.utcnow(), "id": returner_id},
            )

        commits, patched = self._commit_then(come_back)
        with mock.patch.object(retention_service, "GUEST_PURGE_BATCH_SIZE", 1), patched:
            retention_service.purge_inactive_guest_accounts()

        self.assertIn("g-returns", self._guest_uuids(),
                      "a guest active again mid-run was deleted")

    def test_an_outage_stops_the_run_instead_of_skipping_each_guest(self):
        """Isolation is for row-level faults. A dropped connection is not about
        any one guest, so it must reach the outer handler once rather than be
        counted as a skip for every guest left in the list."""
        for i in range(3):
            self._guest(f"g-{i}", days_idle=200)
        self.session.commit()

        with mock.patch.object(OrmSession, "delete", _outage):
            result = retention_service.purge_inactive_guest_accounts()

        self.assertEqual(result.get('skipped_guests'), 0,
                         "an outage was swallowed as per-guest skips")
        self.assertEqual(result.get('purged_guests'), 0)
        self.assertEqual(len(self._guest_uuids()), 3)

    def test_a_failed_commit_is_not_counted_as_purged(self):
        """Counts are credited when a batch commits, not when its savepoint is
        released. A commit that fails rolls the batch back, and the returned
        number is what purge_backlog.py prints to the operator.

        Asserts the return value only. On SQLite the savepoint RELEASE has
        already committed each guest, so the end state cannot show a rollback.
        """
        for i in range(4):
            self._guest(f"g-{i}", days_idle=200)
        self.session.commit()

        real_commit = OrmSession.commit
        calls = []

        def second_commit_fails(s):
            calls.append(1)
            if len(calls) == 2:
                raise OperationalError(
                    "COMMIT", {}, Exception("server closed the connection"))
            return real_commit(s)

        with mock.patch.object(retention_service, "GUEST_PURGE_BATCH_SIZE", 2), \
             mock.patch.object(OrmSession, "commit", second_commit_fails):
            result = retention_service.purge_inactive_guest_accounts()

        self.assertEqual(result.get('purged_guests'), 2,
                         "a batch whose commit failed was reported as purged")


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

    def test_history_follows_its_room(self):
        """Deletable rooms take their history with them. The stuck room's
        history is rolled back with it, because the per-room retry deletes
        history and room in one transaction."""
        self._block_room_deletes()
        stuck = self._orphan_room("r-stuck")
        self._orphan_room("r-a")
        for uuid in ("r-stuck", "r-a"):
            self._history(uuid)
        self._pin_room(stuck)
        self.session.commit()

        db_run_cleanup()

        item_rooms, hint_rooms = self._history_rooms()
        self.assertEqual(item_rooms, {"r-stuck"})
        self.assertEqual(hint_rooms, {"r-stuck"})

    def test_a_failed_chunk_does_not_stop_later_chunks(self):
        """The guard used to sit outside the chunk loop. Chunks of 2 across 5
        rooms, with the stuck room in the first, so later chunks have to run
        after an earlier one failed and was retried."""
        self._block_room_deletes()
        stuck = self._orphan_room("r-0-stuck")
        for i in range(1, 5):
            self._orphan_room(f"r-{i}")
        self._pin_room(stuck)
        self.session.commit()

        with mock.patch.object(poller, "ROOM_CLEANUP_CHUNK", 2):
            db_run_cleanup()

        self.assertEqual(self._room_uuids(), {"r-0-stuck"})

    def test_an_outage_is_not_retried_room_by_room(self):
        """A connection failure hits every chunk alike. Retrying each room
        would turn one failed run into a log line per orphaned room."""
        for i in range(3):
            self._orphan_room(f"r-{i}")
        self.session.commit()

        with mock.patch.object(poller, "_delete_room_chunk", _outage), \
             mock.patch.object(poller, "_delete_rooms_individually") as retry:
            db_run_cleanup()

        retry.assert_not_called()

    def test_clean_run_is_unchanged(self):
        self._orphan_room("r-old")
        self._orphan_room("r-recent", days_since_poll=1)
        self.session.commit()

        db_run_cleanup()

        self.assertEqual(self._room_uuids(), {"r-recent"})


if __name__ == '__main__':
    unittest.main()
