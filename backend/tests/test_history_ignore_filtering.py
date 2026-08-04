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
from app.models import (
    Base, NotifiedItem, UserTrackedSlot, TrackedRoom, DatapackageCache,
    User, UserRoomSubscription, UserIgnoreItem, UserWhitelistItem
)


class TestHistoryIgnoreFiltering(unittest.TestCase):
    """
    Regression coverage for the "isIgnored"/"isWhitelisted" flags on history
    responses. Previously the ignore/whitelist toggle was evaluated entirely
    client-side by matching item names, so item-group rules (which have no
    client-visible membership data) never matched anything in history, even
    though they correctly suppressed notifications server-side. The server
    now computes these flags directly using the same logic as the poller.
    """

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
            'jti': 'test-jti-ignore-filter'
        }
        secret = self.app.config['SECRET_KEY']
        return jwt.encode(payload, secret, algorithm='HS256')

    def _make_room_and_user(self, checksum="checksumA"):
        room = TrackedRoom(
            room_id="ignore-filter-room-uuid",
            tracker_id="test_tracker",
            hostname="archipelago.gg",
            game_checksums_json=json.dumps({"Zelda": checksum}),
            cached_players_json=json.dumps([{"slot_id": 1, "name": "Player1", "game": "Zelda"}])
        )
        self.session.add(room)
        self.session.flush()

        user = User(discord_id="88888", discord_username="ignorefiltertestuser")
        self.session.add(user)
        self.session.flush()

        sub = UserRoomSubscription(user_id=user.id, room_id=room.id, alias="Ignore Filter Room")
        self.session.add(sub)

        slot = UserTrackedSlot(user_id=user.id, room_id=room.id, slot_id=1)
        self.session.add(slot)
        self.session.commit()

        return room, user

    def _add_item_datapackage(self, checksum, item_id, item_name, group_name=None):
        self.session.add(DatapackageCache(
            game="Zelda", checksum=checksum, entity_type='item',
            entity_id=item_id, entity_name=item_name
        ))
        if group_name:
            groups = {group_name: [item_name]}
            self.session.add(DatapackageCache(
                game="Zelda", checksum=checksum, entity_type='item_name_groups_json',
                entity_id=0, entity_name=json.dumps(groups)
            ))
        self.session.commit()

    def _add_notified_item(self, room, item_id, notified_id=1):
        self.session.add(NotifiedItem(
            id=notified_id,
            room_id=room.room_id,
            receiving_slot_id=1,
            sending_slot_id=2,
            item_id=item_id,
            location_id=1000 + item_id,
            item_index=0,
            timestamp=datetime.now(timezone.utc)
        ))
        self.session.commit()

    def _get_item_history(self, user, room_db_id):
        token = self._generate_token(user.id)
        headers = {'Authorization': f'Bearer {token}'}
        res = self.client.get(f'/rooms/{room_db_id}/history/items', headers=headers)
        self.assertEqual(res.status_code, 200)
        return res.get_json()

    def test_group_ignore_is_reflected_in_history(self):
        room, user = self._make_room_and_user(checksum="checksumA")
        self._add_item_datapackage("checksumA", item_id=501, item_name="Boo Buddy", group_name="Boos")
        self._add_notified_item(room, item_id=501)

        self.session.add(UserIgnoreItem(
            user_id=user.id, item_name="Boos", game_name="Zelda", is_group=True
        ))
        self.session.commit()

        history = self._get_item_history(user, room.id)
        self.assertEqual(len(history), 1)
        self.assertTrue(history[0]['isIgnored'], "Group-ignored item should be flagged isIgnored in history")
        self.assertFalse(history[0]['isWhitelisted'])

    def test_single_item_ignore_is_reflected_in_history(self):
        room, user = self._make_room_and_user(checksum="checksumA")
        self._add_item_datapackage("checksumA", item_id=502, item_name="Power Star")
        self._add_notified_item(room, item_id=502)

        self.session.add(UserIgnoreItem(
            user_id=user.id, item_name="Power Star", game_name="Zelda", is_group=False
        ))
        self.session.commit()

        history = self._get_item_history(user, room.id)
        self.assertEqual(len(history), 1)
        self.assertTrue(history[0]['isIgnored'])

    def test_whitelist_overrides_group_ignore(self):
        room, user = self._make_room_and_user(checksum="checksumA")
        self._add_item_datapackage("checksumA", item_id=503, item_name="Boo Buddy", group_name="Boos")
        self._add_notified_item(room, item_id=503)

        self.session.add(UserIgnoreItem(
            user_id=user.id, item_name="Boos", game_name="Zelda", is_group=True
        ))
        self.session.add(UserWhitelistItem(
            user_id=user.id, item_name="Boo Buddy", game_name="Zelda", is_group=False
        ))
        self.session.commit()

        history = self._get_item_history(user, room.id)
        self.assertEqual(len(history), 1)
        self.assertTrue(history[0]['isWhitelisted'])
        self.assertFalse(history[0]['isIgnored'])

    def test_group_ignore_does_not_leak_to_other_game(self):
        room, user = self._make_room_and_user(checksum="checksumA")
        self._add_item_datapackage("checksumA", item_id=504, item_name="Boo Buddy", group_name="Boos")
        self._add_notified_item(room, item_id=504)

        # Rule targets a different game entirely; should not match.
        self.session.add(UserIgnoreItem(
            user_id=user.id, item_name="Boos", game_name="Some Other Game", is_group=True
        ))
        self.session.commit()

        history = self._get_item_history(user, room.id)
        self.assertEqual(len(history), 1)
        self.assertFalse(history[0]['isIgnored'])

    def test_group_ignore_is_version_specific_to_checksum(self):
        """
        If the currently-cached datapackage version for a game has no group data
        for the checksum in play (e.g. a different/older version), a group rule
        for that game must not match items under that checksum.
        """
        room, user = self._make_room_and_user(checksum="checksumB")
        # Item exists under checksumB, but with no item_name_groups_json entry
        # (simulating a version where group data wasn't captured/available).
        self._add_item_datapackage("checksumB", item_id=505, item_name="Boo Buddy", group_name=None)
        self._add_notified_item(room, item_id=505)

        self.session.add(UserIgnoreItem(
            user_id=user.id, item_name="Boos", game_name="Zelda", is_group=True
        ))
        self.session.commit()

        history = self._get_item_history(user, room.id)
        self.assertEqual(len(history), 1)
        self.assertFalse(history[0]['isIgnored'])


if __name__ == '__main__':
    unittest.main()
