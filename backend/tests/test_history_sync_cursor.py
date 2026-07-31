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
from app.models import Base, NotifiedItem, UserTrackedSlot, TrackedRoom, DatapackageCache, User, UserRoomSubscription


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


if __name__ == '__main__':
    unittest.main()
