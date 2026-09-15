"""A pending room resolving to a room another tracker owns (#350).

A tracker imported before its room link was set becomes a pending room. When the
link later names a room already in the app, the sync merges the pending room into
it. It used to re-point that room to the incoming tracker unconditionally, moving
every user linked through the owner onto a tracker none of them chose.

Now the owner keeps the room, and the importing user is merged in unlinked: a
pending room is hidden from the room list, so leaving it pending would make the
import look like it did nothing.
"""
import json
import os
import unittest
from datetime import datetime

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_cheese_pending_merge.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

from app import create_app, Session, engine
from app.models import Base, TrackedRoom, User, UserRoomSubscription, UserTrackedSlot
from app.services.cheese_service import process_cheese_update
from app.utils import CHEESE_LINK_LINKED, CHEESE_LINK_NONE

REAL_ROOM = "real_uuid"
OWNER_PAYLOAD = {'from': 'ct_owner', 'games': []}
INCOMING = {
    'room_link': f'https://archipelago.gg/room/{REAL_ROOM}',
    'games': [],
    'from': 'ct_incoming',
}


def _remove_test_db():
    for suffix in ('', '-wal', '-shm'):
        path = f"{TEST_DB_PATH}{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


class PendingMergeTestBase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.session = Session()

    def tearDown(self):
        self.session.close()
        Session.remove()
        engine.dispose()
        self.app_context.pop()
        _remove_test_db()

    def _user(self, user_id, discord):
        user = User(id=user_id, discord_username=discord, is_guest=False)
        self.session.add(user)
        self.session.flush()
        return user

    def _rooms(self, owner_ct_id="ct_owner"):
        """Room X, linked by one user through its owner, and a pending room for the
        incoming tracker, imported by another user who plays slot 3."""
        owner_user = self._user(1, "owner")
        importer = self._user(2, "importer")

        real = TrackedRoom(
            room_id=REAL_ROOM, hostname="archipelago.gg", tracker_id="ap_trk",
            cheese_tracker_id=owner_ct_id,
            cached_cheese_json=json.dumps(OWNER_PAYLOAD) if owner_ct_id else None,
            cheese_updated_at=datetime(2026, 9, 1) if owner_ct_id else None,
        )
        pending = TrackedRoom(
            room_id="PENDING_DISCOVERY_ct_incoming", hostname="archipelago.gg",
            cheese_tracker_id="ct_incoming",
        )
        self.session.add_all([real, pending])
        self.session.flush()

        self.session.add(UserRoomSubscription(
            user_id=owner_user.id, room_id=real.id, alias="Owner's",
            cheese_link=CHEESE_LINK_LINKED,
        ))
        self.session.add(UserRoomSubscription(
            user_id=importer.id, room_id=pending.id, alias="Imported",
            icon_name='cheese', cheese_link=CHEESE_LINK_LINKED,
        ))
        self.session.add(UserTrackedSlot(
            user_id=importer.id, room_id=pending.id, slot_id=3, track_mode='play',
        ))
        self.session.commit()
        return real.id, pending.id

    def _sync_pending(self, pending_id):
        return process_cheese_update(pending_id, dict(INCOMING), '2026-09-15T10:00:00Z')


class TestOwnedRoomIsNotTaken(PendingMergeTestBase):
    def test_the_room_keeps_its_owner(self):
        real_id, pending_id = self._rooms()

        self._sync_pending(pending_id)

        fresh = Session()
        try:
            real = fresh.get(TrackedRoom, real_id)
            self.assertEqual(real.cheese_tracker_id, "ct_owner")
            self.assertEqual(json.loads(real.cached_cheese_json), OWNER_PAYLOAD,
                             "the incoming tracker's payload was cached onto the owner's room")
            self.assertEqual(real.cheese_updated_at, datetime(2026, 9, 1))
            self.assertEqual(fresh.get(UserRoomSubscription, (1, real_id)).cheese_link,
                             CHEESE_LINK_LINKED, "the owner's user lost their link")
        finally:
            fresh.close()

    def test_the_importer_gets_the_room_unlinked(self):
        real_id, pending_id = self._rooms()

        self.assertEqual(self._sync_pending(pending_id), {})

        fresh = Session()
        try:
            self.assertIsNone(fresh.get(TrackedRoom, pending_id),
                              "a pending room is hidden from the room list; the import would show nothing")
            sub = fresh.get(UserRoomSubscription, (2, real_id))
            self.assertIsNotNone(sub)
            self.assertEqual(sub.alias, "Imported")
            self.assertEqual(sub.cheese_link, CHEESE_LINK_NONE,
                             "linked would authorise claims on a tracker the user never chose")
            slot = fresh.query(UserTrackedSlot).filter_by(user_id=2, slot_id=3).one()
            self.assertEqual(slot.room_id, real_id)
        finally:
            fresh.close()

    def test_an_importer_already_in_the_room_keeps_their_subscription(self):
        real_id, pending_id = self._rooms()
        self.session.add(UserRoomSubscription(
            user_id=2, room_id=real_id, alias="Already here", cheese_link=CHEESE_LINK_LINKED,
        ))
        self.session.commit()

        self._sync_pending(pending_id)

        fresh = Session()
        try:
            sub = fresh.get(UserRoomSubscription, (2, real_id))
            self.assertEqual((sub.alias, sub.cheese_link), ("Already here", CHEESE_LINK_LINKED))
        finally:
            fresh.close()


class TestUnownedRoomStillMerges(PendingMergeTestBase):
    def test_a_room_with_no_tracker_takes_the_incoming_one(self):
        """The merge the guard must not block."""
        real_id, pending_id = self._rooms(owner_ct_id=None)

        self._sync_pending(pending_id)

        fresh = Session()
        try:
            real = fresh.get(TrackedRoom, real_id)
            self.assertEqual(real.cheese_tracker_id, "ct_incoming")
            self.assertEqual(json.loads(real.cached_cheese_json)['from'], 'ct_incoming')
            self.assertIsNone(fresh.get(TrackedRoom, pending_id))
            self.assertIsNotNone(fresh.get(UserRoomSubscription, (2, real_id)))
        finally:
            fresh.close()


if __name__ == '__main__':
    unittest.main()
