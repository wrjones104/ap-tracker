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
one transaction, so no other session ever observes the gap. The archived case is
the one that would be easy to get wrong by reaching for a stricter filter:
archiving is a subscription that still exists, and those rooms must keep polling.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_unwatched.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import Base, TrackedRoom, User, UserRoomSubscription
from app.poller import db_get_active_rooms, db_run_cleanup


class UnwatchedRoomTestBase(unittest.TestCase):
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

    def test_archived_subscription_still_counts_as_watched(self):
        """Archiving keeps the row. A stricter filter would silently stop these."""
        user = self._user("1")
        room = self._room("archived-but-mine")
        self._subscribe(user, room, archived=True)
        self.session.commit()

        self.assertEqual(self._active_uuids(), {"archived-but-mine"})

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


if __name__ == '__main__':
    unittest.main()
