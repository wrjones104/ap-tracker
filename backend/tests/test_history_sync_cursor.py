import os
import sys
import unittest
import json
import jwt
import tempfile
from datetime import datetime, timezone, timedelta

# Create a unique temporary DB for this test process
temp_db_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
TEST_DB_PATH = temp_db_file.name
temp_db_file.close()

os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import Base, NotifiedItem, NotifiedHint, UserTrackedSlot, TrackedRoom, DatapackageCache, User, UserRoomSubscription


class TestHistorySyncCursor(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.session = Session()

    def tearDown(self):
        self.session.close()
        Session.remove()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def _generate_token(self, user_id):
        payload = {
            'user_id': user_id,
            'iat': datetime.now(timezone.utc),
            'exp': datetime.now(timezone.utc) + timedelta(days=1),
            'jti': 'test-jti-123'
        }
        secret = self.app.config['SECRET_KEY']
        return jwt.encode(payload, secret, algorithm='HS256')

    def test_out_of_bounds_cursor_recovery(self):
        room_uuid = "cursor-room-uuid-123"
        room = TrackedRoom(
            room_id=room_uuid,
            tracker_id="test_tracker",
            hostname="archipelago.gg",
            game_checksums_json=json.dumps({"Zelda": "checksum123"}),
            cached_players_json=json.dumps([{"slot_id": 1, "name": "Player1", "game": "Zelda"}])
        )
        self.session.add(room)
        self.session.flush()

        room_db_id = room.id

        user = User(discord_id="99999", discord_username="cursortestuser")
        self.session.add(user)
        self.session.flush()

        sub = UserRoomSubscription(user_id=user.id, room_id=room_db_id, alias="Cursor Room")
        self.session.add(sub)
        self.session.flush()

        slot = UserTrackedSlot(user_id=user.id, room_id=room_db_id, slot_id=1)
        self.session.add(slot)
        self.session.flush()

        # Add 5 items (IDs 1 to 5)
        for idx in range(1, 6):
            self.session.add(NotifiedItem(
                id=idx,
                room_id=room_uuid,
                receiving_slot_id=1,
                sending_slot_id=2,
                item_id=100 + idx,
                location_id=1000 + idx,
                item_index=idx - 1,
                timestamp=datetime.now(timezone.utc)
            ))

        self.session.commit()

        token = self._generate_token(user.id)
        headers = {'Authorization': f'Bearer {token}'}

        # Case 1: Normal in-bounds cursor last_id=2 -> should return items 3, 4, 5
        req_normal = {
            "items": [{"room_db_id": room_db_id, "slot_id": 1, "last_id": 2}],
            "hints": []
        }
        res_normal = self.client.post('/history/sync', json=req_normal, headers=headers)
        self.assertEqual(res_normal.status_code, 200)
        data_normal = res_normal.get_json()
        self.assertEqual(len(data_normal['new_items']), 3)

        # Case 2: Out-of-bounds cursor last_id=5400 (exceeds max_id=5) -> should recover and return items 1 to 5
        req_oob = {
            "items": [{"room_db_id": room_db_id, "slot_id": 1, "last_id": 5400}],
            "hints": []
        }
        res_oob = self.client.post('/history/sync', json=req_oob, headers=headers)
        self.assertEqual(res_oob.status_code, 200)
        data_oob = res_oob.get_json()
        self.assertEqual(len(data_oob['new_items']), 5)
        self.assertEqual(data_oob['item_watermarks'][f"{room_db_id}_1"], 5)

    def _room_with_hints(self, user, room_uuid, hint_count, start, item_base):
        room = TrackedRoom(
            room_id=room_uuid,
            tracker_id=f"tracker-{room_uuid}",
            hostname="archipelago.gg",
            game_checksums_json=json.dumps({"Zelda": "checksum123"}),
            cached_players_json=json.dumps([
                {"slot_id": 1, "name": "Player1", "game": "Zelda"},
                {"slot_id": 2, "name": "Player2", "game": "Zelda"},
            ])
        )
        self.session.add(room)
        self.session.flush()
        self.session.add(UserRoomSubscription(user_id=user.id, room_id=room.id, alias=room_uuid))
        self.session.add(UserTrackedSlot(user_id=user.id, room_id=room.id, slot_id=1))
        for idx in range(hint_count):
            ts = start + timedelta(minutes=idx)
            self.session.add(NotifiedHint(
                room_id=room_uuid,
                item_owner_id=1,
                location_owner_id=2,
                item_id=item_base + idx,
                location_id=item_base + idx,
                timestamp=ts,
                updated_at=ts,
            ))
        self.session.flush()
        return room.id

    def test_room_without_cursor_keeps_hints_queued_behind_other_rooms(self):
        # Two rooms with no hint cursor (fresh login, reinstall, "clear history").
        # Room A's 150 older hints fill the first batch. Room B must not be
        # handed "now" as its cursor, or its 5 newer hints are never sent. #421.
        user = User(discord_id="88888", discord_username="hintcursoruser")
        self.session.add(user)
        self.session.flush()
        room_a = self._room_with_hints(user, "hint-room-a", 150, datetime(2026, 9, 1), 10_000)
        room_b = self._room_with_hints(user, "hint-room-b", 5, datetime(2026, 10, 5), 20_000)
        self.session.commit()

        headers = {'Authorization': f'Bearer {self._generate_token(user.id)}'}

        # Mirror the app: send each room's stored cursor, store only the keys
        # the server returns, and stop on an empty batch.
        cursors = {str(room_a): None, str(room_b): None}
        received = {"hint-room-a": 0, "hint-room-b": 0}
        for _ in range(10):
            res = self.client.post('/history/sync', json={
                "items": [],
                "hints": [{"room_db_id": int(r), "last_updated": c} for r, c in cursors.items()],
            }, headers=headers)
            self.assertEqual(res.status_code, 200, res.get_json())
            data = res.get_json()
            for hint in data['updated_hints']:
                received["hint-room-a" if hint['room_db_id'] == room_a else "hint-room-b"] += 1
            cursors.update(data['hint_watermarks'])
            if not data['updated_hints']:
                break

        self.assertEqual(received, {"hint-room-a": 150, "hint-room-b": 5})
        # Once caught up, both rooms carry a real cursor again.
        self.assertIsNotNone(cursors[str(room_a)])
        self.assertIsNotNone(cursors[str(room_b)])

    def test_room_without_hints_gets_a_cursor_when_the_batch_is_not_full(self):
        user = User(discord_id="77777", discord_username="emptyhintroomuser")
        self.session.add(user)
        self.session.flush()
        room_a = self._room_with_hints(user, "busy-room", 3, datetime(2026, 9, 1), 30_000)
        room_b = self._room_with_hints(user, "quiet-room", 0, datetime(2026, 9, 1), 40_000)
        self.session.commit()

        headers = {'Authorization': f'Bearer {self._generate_token(user.id)}'}
        res = self.client.post('/history/sync', json={
            "items": [],
            "hints": [{"room_db_id": room_a, "last_updated": None},
                      {"room_db_id": room_b, "last_updated": None}],
        }, headers=headers)

        self.assertEqual(res.status_code, 200, res.get_json())
        watermarks = res.get_json()['hint_watermarks']
        self.assertEqual(len(res.get_json()['updated_hints']), 3)
        # A batch that is not full proves the quiet room has no hints yet.
        self.assertIsNotNone(watermarks.get(str(room_b)))


if __name__ == '__main__':
    unittest.main()
