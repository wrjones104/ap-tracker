"""
Tests for the size of GET /users/me/tracked-slots.

The app calls this endpoint on every push and every background sync. It used to
carry each room's whole player list, which made it the largest source of
internet egress (about 152 KB per call on prod) while no app version read it.
See #412. These tests lock down that the list stays out while the per-slot
fields that are built from it stay in.
"""
import json
import os
import sys
import unittest

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_tracked_slots_payload.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import Base, User, TrackedRoom, UserRoomSubscription, UserTrackedSlot

ROOM_UUID = 'room-uuid-payload'
TRACKED_SLOT_ID = 7
PLAYER_COUNT = 500


def _make_token(app, user_id):
    """Generate a JWT for the given user_id matching the token_required format."""
    import jwt as pyjwt
    import uuid
    from datetime import datetime, timezone, timedelta
    payload = {
        'user_id': user_id,
        'jti': str(uuid.uuid4()),
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')


def _remove_test_db():
    for suffix in ('', '-wal', '-shm'):
        path = f"{TEST_DB_PATH}{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


class TestTrackedSlotsPayload(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.client = self.app.test_client()

        # A large async: hundreds of players, of whom the user tracks one.
        players = [
            {
                'slot_id': i,
                'name': f'Player{i}',
                'alias': f'Alias {i}',
                'game': 'A Link to the Past',
                'is_finished': False,
                'total_locations': 216,
            }
            for i in range(1, PLAYER_COUNT + 1)
        ]

        session = Session()
        try:
            user = User(discord_id='user_payload', discord_username='PayloadUser')
            session.add(user)
            session.flush()
            self.user_id = user.id

            room = TrackedRoom(room_id=ROOM_UUID, cached_players_json=json.dumps(players))
            session.add(room)
            session.flush()

            session.add(UserRoomSubscription(user_id=user.id, room_id=room.id, alias='Big Async'))
            session.flush()
            session.add(UserTrackedSlot(user_id=user.id, room_id=room.id, slot_id=TRACKED_SLOT_ID))
            session.commit()
        finally:
            Session.remove()

        self.token = _make_token(self.app, self.user_id)

    def tearDown(self):
        Session.remove()
        # Before unlinking, so the pool cannot go on serving an unlinked inode on Linux.
        engine.dispose()
        _remove_test_db()

    def _get(self):
        response = self.client.get(
            '/users/me/tracked-slots',
            headers={'Authorization': f'Bearer {self.token}'}
        )
        self.assertEqual(response.status_code, 200)
        return response

    def test_room_player_list_is_not_sent(self):
        rooms = self._get().get_json()
        self.assertEqual(len(rooms), 1)
        self.assertNotIn('players', rooms[0])

    def test_tracked_slot_still_resolves_from_the_player_list(self):
        # The list is still read on the server: it is where each tracked slot's
        # name, alias, game and location count come from.
        slot = self._get().get_json()[0]['tracked_slots'][0]
        self.assertEqual(slot['slot_id'], TRACKED_SLOT_ID)
        self.assertEqual(slot['player_name'], f'Player{TRACKED_SLOT_ID}')
        self.assertEqual(slot['player_alias'], f'Alias {TRACKED_SLOT_ID}')
        self.assertEqual(slot['game'], 'A Link to the Past')
        self.assertEqual(slot['total_locations'], 216)

    def test_response_size_does_not_grow_with_room_size(self):
        # One tracked slot in a 500-player room. With the list included this was
        # about 100 KB; without it, one room and one slot come to about 1 KB.
        size = len(self._get().get_data())
        self.assertLess(size, 4096, f'tracked-slots response is {size} bytes')


if __name__ == '__main__':
    unittest.main()
