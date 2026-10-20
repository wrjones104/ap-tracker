"""Rooms nobody subscribes to are not polled, so the janitor can collect them.

The loop this closes: db_get_active_rooms selected on is_complete and
is_suspended only, so a room with zero subscribers was polled like any other.
Every successful poll stamps last_successful_poll, and that is the same field
db_run_cleanup reads to decide a room has been unused long enough to delete. An
upstream-active room that nobody tracks therefore refreshed its own liveness
forever and was never collected. Production held 1,651 of them.

Suspension is not the escape hatch it looks like: it only arrives after 30 days
of no item or hint activity upstream, so a long-running async that nobody
tracks stays out of reach of both rules indefinitely.

What the filter must NOT do is drop a room during the window where it exists
without a subscription. Both creation paths -- rooms_routes.add_room and
api_cheese.import_available_cheese_rooms -- add the room and the subscription in
one transaction, so no other session ever observes the gap.

Archiving pauses a room rather than orphaning it (#347). A room whose every
subscription is archived is not polled, suspended or healed, because the poller
recorded nothing for archived subscriptions anyway. But the subscription still
exists, so the janitor must never collect the room: archived history is kept.
"""
import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_unwatched.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import (
    Base, NotifiedHint, NotifiedItem, TrackedRoom, User, UserRoomSubscription,
)
from app.poller import (
    db_check_stale_rooms, db_get_active_rooms, db_get_suspended_rooms_for_healing,
    db_run_cleanup, run_janitor,
)


class UnwatchedRoomTestBase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.session = Session()

    def tearDown(self):
        self.session.close()
        Session.remove()
        # Before unlinking the file, not after. Without this the pool keeps
        # connections open against the path; on Linux the unlink succeeds and
        # those connections go on serving the now-unlinked inode, so the next
        # test's create_all builds its tables there while a freshly opened
        # connection sees an empty file and raises "no such table". On Windows
        # the unlink fails while a handle is open and the except below hides it,
        # which is why this only ever failed in CI.
        engine.dispose()
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def _user(self, discord_id):
        user = User(discord_id=discord_id, discord_username=f"u{discord_id}")
        self.session.add(user)
        self.session.flush()
        return user

    def _room(self, uuid, last_poll=None, suspended=False, complete=False,
              cheese_tracker_id=None):
        room = TrackedRoom(
            room_id=uuid, tracker_id="t", hostname="archipelago.gg",
            last_successful_poll=last_poll, is_suspended=suspended,
            is_complete=complete, cheese_tracker_id=cheese_tracker_id,
        )
        self.session.add(room)
        self.session.flush()
        return room

    def _subscribe(self, user, room, archived=False):
        sub = UserRoomSubscription(
            user_id=user.id, room_id=room.id, alias="a", is_archived=archived,
        )
        self.session.add(sub)
        self.session.flush()
        return sub

    def _active_uuids(self):
        rooms = db_get_active_rooms()
        self.assertIsNotNone(rooms, "db_get_active_rooms returned None (query error)")
        return {r.room_id for r in rooms}


class TestActiveRoomSelection(UnwatchedRoomTestBase):
    def test_room_with_no_subscribers_is_not_polled(self):
        """The whole point. Before the fix this room came back and kept itself alive."""
        user = self._user("1")
        watched = self._room("watched")
        self._subscribe(user, watched)
        self._room("orphan")
        self.session.commit()

        self.assertEqual(self._active_uuids(), {"watched"})

    def test_room_archived_by_everyone_is_paused(self):
        """#347: the poller stored nothing for archived subscriptions, so polling
        these only cost a fetch per cycle."""
        user = self._user("1")
        room = self._room("archived-by-me")
        self._subscribe(user, room, archived=True)
        self.session.commit()

        self.assertEqual(self._active_uuids(), set())

    def test_one_unarchived_subscriber_keeps_it_polled(self):
        """Another user's archive must not pause a room someone still follows."""
        a, b = self._user("1"), self._user("2")
        room = self._room("shared")
        self._subscribe(a, room, archived=True)
        self._subscribe(b, room)
        self.session.commit()

        self.assertEqual(self._active_uuids(), {"shared"})

    def test_unarchiving_resumes_polling(self):
        """Pausing is not permanent: unarchive and the room is back on the list."""
        user = self._user("1")
        room = self._room("paused")
        self._subscribe(user, room, archived=True)
        self.session.commit()
        # The query's Session.remove() detaches everything loaded above.
        user_id, room_id = user.id, room.id
        self.assertEqual(self._active_uuids(), set())

        sub = self.session.query(UserRoomSubscription).filter_by(
            user_id=user_id, room_id=room_id).one()
        sub.is_archived = False
        self.session.commit()

        self.assertEqual(self._active_uuids(), {"paused"})

    def test_cheese_room_with_a_subscriber_is_still_polled(self):
        """A Cheese-linked room is reached through the same list; only the
        subscription decides, not where the room came from."""
        user = self._user("1")
        room = self._room("PENDING_DISCOVERY_abc", cheese_tracker_id="abc")
        self._subscribe(user, room)
        self.session.commit()

        self.assertEqual(self._active_uuids(), {"PENDING_DISCOVERY_abc"})

    def test_cheese_room_nobody_subscribes_to_is_not_polled(self):
        """An imported tracker whose subscription is gone stops costing a Cheese
        poll as well as an Archipelago one -- both tasks hang off this list."""
        self._room("PENDING_DISCOVERY_abc", cheese_tracker_id="abc")
        self.session.commit()

        self.assertEqual(self._active_uuids(), set())

    def test_losing_the_last_subscriber_stops_the_polling(self):
        """Unsubscribing is what creates an orphan in production."""
        user = self._user("1")
        room = self._room("shared")
        sub = self._subscribe(user, room)
        self.session.commit()
        self.assertEqual(self._active_uuids(), {"shared"})

        self.session.delete(sub)
        self.session.commit()

        self.assertEqual(self._active_uuids(), set())

    def test_one_remaining_subscriber_keeps_it_polled(self):
        """Two trackers, one leaves. The room is still somebody's."""
        a, b = self._user("1"), self._user("2")
        room = self._room("shared")
        sub_a = self._subscribe(a, room)
        self._subscribe(b, room)
        self.session.commit()

        self.session.delete(sub_a)
        self.session.commit()

        self.assertEqual(self._active_uuids(), {"shared"})

    def test_suspended_and_complete_rooms_are_still_excluded(self):
        """The new filter is additional, not a replacement."""
        user = self._user("1")
        for uuid, kwargs in (
            ("suspended", {"suspended": True}),
            ("complete", {"complete": True}),
        ):
            room = self._room(uuid, **kwargs)
            self._subscribe(user, room)
        self.session.commit()

        self.assertEqual(self._active_uuids(), set())


class TestStaleCheckSkipsUnwatched(UnwatchedRoomTestBase):
    """db_check_stale_rooms carries the same filter, and not by accident.

    Suspending a room nothing polls achieves nothing, and every room it does
    suspend joins the healing pool, which then fetches room_status over HTTP for
    it every two hours (#345). The janitor's call order happens to delete
    orphaned rooms before this runs, but that is ordering rather than an
    invariant, and it does not hold during the 30-day drain after the polling
    filter ships -- the orphans exist and are not yet old enough to delete.
    """

    def test_unwatched_room_is_not_suspended(self):
        room = self._room("orphan", last_poll=datetime.utcnow())
        room.last_remote_activity = datetime.utcnow() - timedelta(days=45)
        self.session.commit()

        db_check_stale_rooms()
        self.session.expire_all()

        stale = self.session.query(TrackedRoom).filter_by(room_id="orphan").first()
        self.assertFalse(
            stale.is_suspended,
            "an unwatched room was suspended, which only feeds the healing pool")

    def test_watched_room_is_still_suspended_when_stale(self):
        """The filter must not stop the suspension it exists to do."""
        user = self._user("1")
        room = self._room("mine", last_poll=datetime.utcnow())
        room.last_remote_activity = datetime.utcnow() - timedelta(days=45)
        self._subscribe(user, room)
        self.session.commit()

        db_check_stale_rooms()
        self.session.expire_all()

        stale = self.session.query(TrackedRoom).filter_by(room_id="mine").first()
        self.assertTrue(stale.is_suspended)

    def test_archived_only_room_is_not_suspended(self):
        """A paused room is not polled, so suspending it would only feed healing."""
        user = self._user("1")
        room = self._room("archived", last_poll=datetime.utcnow())
        room.last_remote_activity = datetime.utcnow() - timedelta(days=45)
        self._subscribe(user, room, archived=True)
        self.session.commit()

        db_check_stale_rooms()
        self.session.expire_all()

        stale = self.session.query(TrackedRoom).filter_by(room_id="archived").first()
        self.assertFalse(stale.is_suspended)

    def test_watched_room_with_recent_activity_is_left_alone(self):
        user = self._user("1")
        room = self._room("active", last_poll=datetime.utcnow())
        room.last_remote_activity = datetime.utcnow() - timedelta(days=2)
        self._subscribe(user, room)
        self.session.commit()

        db_check_stale_rooms()
        self.session.expire_all()

        fresh = self.session.query(TrackedRoom).filter_by(room_id="active").first()
        self.assertFalse(fresh.is_suspended)


class TestStaleCheckActivitySources(UnwatchedRoomTestBase):
    """Which activity keeps a watched room from being suspended.

    db_check_stale_rooms used to ask each room for its latest item and latest
    hint. It now collects every room with history inside the window in one
    scan per table, and only probes for any history at all when a room has no
    remote activity on record. These pin the decisions so the rewrite cannot
    drift from what the per-room version did.
    """

    def _watched_room(self, uuid, remote_days_ago=None):
        user = self._user(uuid)
        room = self._room(uuid, last_poll=datetime.utcnow())
        if remote_days_ago is not None:
            room.last_remote_activity = datetime.utcnow() - timedelta(days=remote_days_ago)
        self._subscribe(user, room)
        return room

    def _item(self, uuid, days_ago, index=1):
        self.session.add(NotifiedItem(
            room_id=uuid, receiving_slot_id=1, sending_slot_id=2, item_id=1,
            location_id=index, item_index=index,
            timestamp=datetime.utcnow() - timedelta(days=days_ago),
        ))

    def _hint(self, uuid, days_ago):
        self.session.add(NotifiedHint(
            room_id=uuid, item_owner_id=1, location_owner_id=2, item_id=1,
            location_id=1, timestamp=datetime.utcnow() - timedelta(days=days_ago),
        ))

    def _suspended(self, uuid):
        db_check_stale_rooms()
        self.session.expire_all()
        return self.session.query(TrackedRoom).filter_by(room_id=uuid).one().is_suspended

    def test_recent_item_keeps_room_active_despite_old_remote_activity(self):
        self._watched_room("r", remote_days_ago=45)
        self._item("r", days_ago=2)
        self.session.commit()
        self.assertFalse(self._suspended("r"))

    def test_recent_hint_keeps_room_active(self):
        self._watched_room("r", remote_days_ago=45)
        self._hint("r", days_ago=2)
        self.session.commit()
        self.assertFalse(self._suspended("r"))

    def test_only_old_history_and_no_remote_activity_is_suspended(self):
        self._watched_room("r")
        self._item("r", days_ago=45)
        self._hint("r", days_ago=40)
        self.session.commit()
        self.assertTrue(self._suspended("r"))

    def test_old_history_but_recent_remote_activity_is_left_alone(self):
        """The case that matters if RETENTION_DAYS is ever set below 30."""
        self._watched_room("r", remote_days_ago=3)
        self._item("r", days_ago=45)
        self.session.commit()
        self.assertFalse(self._suspended("r"))

    def test_room_with_no_activity_on_record_is_left_alone(self):
        """Never seen doing anything is not the same as gone quiet."""
        self._watched_room("r")
        self.session.commit()
        self.assertFalse(self._suspended("r"))

    def test_another_rooms_recent_history_does_not_count(self):
        self._watched_room("quiet", remote_days_ago=45)
        self._item("quiet", days_ago=45)
        self._watched_room("busy")
        self._item("busy", days_ago=1)
        self.session.commit()
        self.assertTrue(self._suspended("quiet"))
        self.assertFalse(self._suspended("busy"))


class TestJanitorRunsOffTheSupervisorLoop(unittest.TestCase):
    """run_janitor is started as a task and never awaited by the supervisor, so
    it has to run its steps in order and keep its own failures to itself."""

    STEPS = ("db_run_cleanup", "db_check_stale_rooms", "run_all_retention_tasks")

    def _run(self, failing_step=None):
        calls = []

        def make(name):
            def step():
                calls.append(name)
                if name == failing_step:
                    raise RuntimeError("boom")
            return step

        loop = asyncio.new_event_loop()
        try:
            with mock.patch.multiple("app.poller", **{n: make(n) for n in self.STEPS}):
                loop.run_until_complete(run_janitor(loop))
        finally:
            loop.close()
        return calls

    def test_runs_all_three_steps_in_order(self):
        self.assertEqual(self._run(), list(self.STEPS))

    def test_failure_is_logged_not_raised(self):
        """Nothing awaits the task, so an exception that escaped would only
        surface as 'Task exception was never retrieved' at shutdown."""
        with self.assertLogs(level="ERROR") as logs:
            calls = self._run(failing_step="db_run_cleanup")
        self.assertEqual(calls, ["db_run_cleanup"])
        self.assertIn("[JANITOR] Daily cleanup failed", logs.output[0])


class TestHealingSkipsUnwatched(UnwatchedRoomTestBase):
    """db_get_suspended_rooms_for_healing carries the same filter (#345).

    Each room it returns costs an HTTP request to room_status every two hours,
    and reviving a room nobody watches is pointless: db_get_active_rooms would
    still not return it, so it is never polled.
    """

    def _healing_uuids(self):
        return {r['room_uuid'] for r in db_get_suspended_rooms_for_healing()}

    def test_unwatched_suspended_room_is_not_healed(self):
        self._room("orphan", suspended=True)
        self.session.commit()

        self.assertEqual(self._healing_uuids(), set())

    def test_watched_suspended_room_is_still_healed(self):
        """The filter must not stop the healing it exists to do. A room archived
        by everyone is paused, so healing it is skipped, as polling is."""
        user = self._user("1")
        for uuid, archived in (("mine", False), ("archived-by-me", True)):
            room = self._room(uuid, suspended=True)
            self._subscribe(user, room, archived=archived)
        self.session.commit()

        self.assertEqual(self._healing_uuids(), {"mine"})

    def test_room_is_healed_again_once_someone_subscribes(self):
        """Skipping an orphan is not permanent: gaining a subscriber puts it
        straight back in the pool."""
        self._room("returning", suspended=True)
        self.session.commit()
        self.assertEqual(self._healing_uuids(), set())

        # The query's Session.remove() detached everything loaded above.
        room = self.session.query(TrackedRoom).filter_by(room_id="returning").one()
        self._subscribe(self._user("1"), room)
        self.session.commit()

        self.assertEqual(self._healing_uuids(), {"returning"})


class TestJanitorCanNowCollect(UnwatchedRoomTestBase):
    def test_the_loop_is_closed_end_to_end(self):
        """The behaviour the issue is actually about.

        An orphaned room whose last poll is recent is not yet deletable, and
        before the fix it never became deletable because polling kept moving
        that timestamp. Freezing it is what lets the existing 30-day rule in
        db_run_cleanup finish the job.
        """
        room = self._room("orphan", last_poll=datetime.utcnow())
        self.session.commit()

        # Not yet: the 30-day window has not passed.
        db_run_cleanup()
        self.assertIsNotNone(
            self.session.query(TrackedRoom).filter_by(room_id="orphan").first())

        # It is excluded from polling, so nothing refreshes the timestamp and
        # the window can actually elapse. Simulate that elapsing.
        self.assertNotIn("orphan", self._active_uuids())

        stale = self.session.query(TrackedRoom).filter_by(room_id="orphan").first()
        stale.last_successful_poll = datetime.utcnow() - timedelta(days=31)
        self.session.commit()

        db_run_cleanup()
        self.session.expire_all()
        self.assertIsNone(
            self.session.query(TrackedRoom).filter_by(room_id="orphan").first(),
            "the janitor still cannot collect a room nothing polls")

    def test_archived_room_is_never_collected(self):
        """Pausing stops the polls that kept last_successful_poll fresh, so an
        archived room soon looks old. The janitor must still keep it: the
        subscription exists, and archiving promises to keep the history."""
        user = self._user("1")
        room = self._room("archived", last_poll=datetime.utcnow() - timedelta(days=90))
        self._subscribe(user, room, archived=True)
        self.session.commit()

        db_run_cleanup()
        self.session.expire_all()
        self.assertIsNotNone(
            self.session.query(TrackedRoom).filter_by(room_id="archived").first(),
            "the janitor deleted a room the user had only archived")


if __name__ == '__main__':
    unittest.main()
