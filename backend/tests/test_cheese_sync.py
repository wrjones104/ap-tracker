import os
import unittest
from unittest.mock import patch, MagicMock
import requests
from datetime import datetime

# Set up test DB and config before importing the app
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_ap_tracker.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno=' # Valid Fernet key

from backend.app import create_app, Session, engine
from backend.app.models import Base, User, TrackedRoom, UserRoomSubscription, UserTrackedSlot
from backend.app.api_cheese import setup_cheese_user_task
from backend.app.encryption import encrypt_api_key

class TestCheeseSync(unittest.TestCase):
    def setUp(self):
        # Create Flask app and context
        self.app = create_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        # Ensure database is clean and has tables
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        
        self.session = Session()

    def tearDown(self):
        self.session.close()
        Session.remove()
        engine.dispose()
        self.app_context.pop()
        
        # Clean up database file
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception as e:
                print(f"Failed to remove test DB: {e}")

    @patch('backend.app.api_cheese.requests.Session')
    def test_setup_cheese_user_task(self, mock_session_cls):
        # Create a mock session instance
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        
        # Set up responses
        # 1. /user/self
        mock_me_resp = MagicMock()
        mock_me_resp.ok = True
        mock_me_resp.json.return_value = {
            'id': 12345,
            'discord_username': 'test_discord_user'
        }
        
        # 2. /dashboard/tracker
        mock_dash_resp = MagicMock()
        mock_dash_resp.ok = True
        mock_dash_resp.json.return_value = [
            {
                'tracker_id': 'ct_room_1',
                'room_link': 'https://archipelago.gg/room/test_room_uuid',
                'title': 'Test Room',
                'dashboard_override_visibility': True
            }
        ]
        
        # 3. /tracker/ct_room_1
        mock_detail_resp = MagicMock()
        mock_detail_resp.ok = True
        mock_detail_resp.json.return_value = {
            'updated_at': '2026-06-23T10:00:00Z',
            'games': [
                {
                    'id': 999,
                    'position': 1,
                    'claimed_by_ct_user_id': 12345,
                    'effective_discord_username': 'test_discord_user'
                }
            ]
        }
        
        # Map calls
        def mock_get(url, *args, **kwargs):
            if '/user/self' in url:
                return mock_me_resp
            elif '/dashboard/tracker' in url:
                return mock_dash_resp
            elif '/tracker/ct_room_1' in url:
                return mock_detail_resp
            return MagicMock()
            
        mock_session.get.side_effect = mock_get
        
        # Create test user in DB
        encrypted_key = encrypt_api_key("fake_api_key")
        user = User(
            id=1,
            discord_username="test_discord_user",
            cheese_api_key=encrypted_key,
            cheese_user_id=12345,
            is_syncing_cheese=True,
            is_guest=False
        )
        self.session.add(user)
        self.session.commit()
        
        # Run setup_cheese_user_task
        setup_cheese_user_task(self.app, user.id)
        
        # Re-query user and check outcomes
        fresh_session = Session()
        updated_user = fresh_session.query(User).get(user.id)
        self.assertFalse(updated_user.is_syncing_cheese)
        self.assertEqual(updated_user.cheese_user_id, 12345)
        
        # Verify rooms are synced
        room = fresh_session.query(TrackedRoom).filter_by(cheese_tracker_id='ct_room_1').first()
        self.assertIsNotNone(room)
        self.assertEqual(room.room_id, 'test_room_uuid')
        
        # Verify sub is created
        sub = fresh_session.query(UserRoomSubscription).filter_by(user_id=user.id, room_id=room.id).first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.alias, 'Test Room')
        
        # Verify slot is tracked
        slot = fresh_session.query(UserTrackedSlot).filter_by(user_id=user.id, room_id=room.id, slot_id=1).first()
        self.assertIsNotNone(slot)
        
        fresh_session.close()

    @patch('backend.app.api_cheese.requests.Session')
    def test_setup_cheese_user_task_pruning_shared_room(self, mock_session_cls):
        # Create a mock session instance
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        
        # Set up responses
        # 1. /user/self
        mock_me_resp = MagicMock()
        mock_me_resp.ok = True
        mock_me_resp.json.return_value = {
            'id': 12345,
            'discord_username': 'test_discord_user'
        }
        
        # 2. /dashboard/tracker (returns user's tracker ID ct_room_user_B)
        mock_dash_resp = MagicMock()
        mock_dash_resp.ok = True
        mock_dash_resp.json.return_value = [
            {
                'tracker_id': 'ct_room_user_B',
                'room_link': 'https://archipelago.gg/room/shared_room_uuid',
                'title': 'Shared Room',
                'dashboard_override_visibility': True
            }
        ]
        
        # 3. /tracker/ct_room_user_B
        mock_detail_resp = MagicMock()
        mock_detail_resp.ok = True
        mock_detail_resp.json.return_value = {
            'updated_at': '2026-06-23T10:00:00Z',
            'games': [
                {
                    'id': 999,
                    'position': 1,
                    'claimed_by_ct_user_id': 12345,
                    'effective_discord_username': 'test_discord_user'
                }
            ]
        }
        
        def mock_get(url, *args, **kwargs):
            if '/user/self' in url:
                return mock_me_resp
            elif '/dashboard/tracker' in url:
                return mock_dash_resp
            elif '/tracker/ct_room_user_B' in url:
                return mock_detail_resp
            return MagicMock()
            
        mock_session.get.side_effect = mock_get
        
        # Pre-create the room linked to User A's cheese_tracker_id (ct_room_user_A)
        room = TrackedRoom(
            room_id='shared_room_uuid',
            hostname='archipelago.gg',
            cheese_tracker_id='ct_room_user_A'
        )
        self.session.add(room)
        self.session.flush()
        room_db_id = room.id
        
        # Create test user (User B) in DB
        encrypted_key = encrypt_api_key("fake_api_key")
        user = User(
            id=1,
            discord_username="test_discord_user",
            cheese_api_key=encrypted_key,
            cheese_user_id=12345,
            is_syncing_cheese=True,
            is_guest=False
        )
        self.session.add(user)
        self.session.flush()
        user_db_id = user.id
        
        # Pre-subscribe User B to this room
        sub = UserRoomSubscription(
            user_id=user_db_id,
            room_id=room_db_id,
            alias='Shared Room',
            is_archived=False
        )
        self.session.add(sub)
        self.session.commit()
        
        # Run setup_cheese_user_task
        setup_cheese_user_task(self.app, user_db_id)
        
        # Verify room is still linked to ct_room_user_A (not overwritten)
        fresh_session = Session()
        room_check = fresh_session.query(TrackedRoom).filter_by(room_id='shared_room_uuid').first()
        self.assertEqual(room_check.cheese_tracker_id, 'ct_room_user_A')
        
        # CRITICAL VERIFICATION: Verify the subscription was NOT pruned/deleted!
        sub_check = fresh_session.query(UserRoomSubscription).filter_by(user_id=user_db_id, room_id=room_db_id).first()
        self.assertIsNotNone(sub_check)
        self.assertEqual(sub_check.alias, 'Shared Room')
        
        fresh_session.close()

    @patch('backend.app.api_cheese.requests.Session')
    def test_setup_cheese_user_task_network_failure_does_not_prune(self, mock_session_cls):
        # Create a mock session instance
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        
        # Set up responses
        # 1. /user/self
        mock_me_resp = MagicMock()
        mock_me_resp.ok = True
        mock_me_resp.json.return_value = {
            'id': 12345,
            'discord_username': 'test_discord_user'
        }
        
        # 2. /dashboard/tracker (returns TWO trackers: ct_room_1 and ct_room_2)
        mock_dash_resp = MagicMock()
        mock_dash_resp.ok = True
        mock_dash_resp.json.return_value = [
            {
                'tracker_id': 'ct_room_1',
                'room_link': 'https://archipelago.gg/room/room_1_uuid',
                'title': 'Room 1',
                'dashboard_override_visibility': True
            },
            {
                'tracker_id': 'ct_room_2',
                'room_link': 'https://archipelago.gg/room/room_2_uuid',
                'title': 'Room 2',
                'dashboard_override_visibility': True
            }
        ]
        
        # 3. /tracker/ct_room_1 (succeeds)
        mock_detail_1_resp = MagicMock()
        mock_detail_1_resp.ok = True
        mock_detail_1_resp.json.return_value = {
            'updated_at': '2026-06-23T10:00:00Z',
            'games': [
                {
                    'id': 101,
                    'position': 1,
                    'claimed_by_ct_user_id': 12345,
                    'effective_discord_username': 'test_discord_user'
                }
            ]
        }
        
        # Map calls: ct_room_1 succeeds, ct_room_2 raises timeout
        def mock_get(url, *args, **kwargs):
            if '/user/self' in url:
                return mock_me_resp
            elif '/dashboard/tracker' in url:
                return mock_dash_resp
            elif '/tracker/ct_room_1' in url:
                return mock_detail_1_resp
            elif '/tracker/ct_room_2' in url:
                raise requests.exceptions.Timeout("Connection timed out")
            return MagicMock()
            
        mock_session.get.side_effect = mock_get
        
        # Pre-create room 2
        room_2 = TrackedRoom(
            room_id='room_2_uuid',
            hostname='archipelago.gg',
            cheese_tracker_id='ct_room_2'
        )
        self.session.add(room_2)
        self.session.flush()
        room_2_db_id = room_2.id
        
        # Create test user in DB
        encrypted_key = encrypt_api_key("fake_api_key")
        user = User(
            id=1,
            discord_username="test_discord_user",
            cheese_api_key=encrypted_key,
            cheese_user_id=12345,
            is_syncing_cheese=True,
            is_guest=False
        )
        self.session.add(user)
        self.session.flush()
        user_db_id = user.id
        
        # Pre-subscribe user to room 2 with custom alias and icon
        sub_2 = UserRoomSubscription(
            user_id=user_db_id,
            room_id=room_2_db_id,
            alias='My Custom Big Room',
            icon_name='custom_icon',
            is_archived=False
        )
        self.session.add(sub_2)
        self.session.commit()
        
        # Run setup_cheese_user_task
        setup_cheese_user_task(self.app, user_db_id)
        
        # Verify room 2's subscription was NOT pruned/deleted and alias/icon are intact
        fresh_session = Session()
        sub_check = fresh_session.query(UserRoomSubscription).filter_by(user_id=user_db_id, room_id=room_2_db_id).first()
        self.assertIsNotNone(sub_check)
        self.assertEqual(sub_check.alias, 'My Custom Big Room')
        self.assertEqual(sub_check.icon_name, 'custom_icon')
        fresh_session.close()

    @patch('backend.app.api_cheese.requests.Session')
    def test_setup_cheese_user_task_pruning_unlinked_room(self, mock_session_cls):
        # Create a mock session instance
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        
        # Set up responses
        # 1. /user/self
        mock_me_resp = MagicMock()
        mock_me_resp.ok = True
        mock_me_resp.json.return_value = {
            'id': 12345,
            'discord_username': 'test_discord_user'
        }
        
        # 2. /dashboard/tracker (returns ONLY ct_room_1, ct_room_2 has been deleted/unlinked)
        mock_dash_resp = MagicMock()
        mock_dash_resp.ok = True
        mock_dash_resp.json.return_value = [
            {
                'tracker_id': 'ct_room_1',
                'room_link': 'https://archipelago.gg/room/room_1_uuid',
                'title': 'Room 1',
                'dashboard_override_visibility': True
            }
        ]
        
        # 3. /tracker/ct_room_1 (succeeds)
        mock_detail_1_resp = MagicMock()
        mock_detail_1_resp.ok = True
        mock_detail_1_resp.json.return_value = {
            'updated_at': '2026-06-23T10:00:00Z',
            'games': [
                {
                    'id': 101,
                    'position': 1,
                    'claimed_by_ct_user_id': 12345,
                    'effective_discord_username': 'test_discord_user'
                }
            ]
        }
        
        def mock_get(url, *args, **kwargs):
            if '/user/self' in url:
                return mock_me_resp
            elif '/dashboard/tracker' in url:
                return mock_dash_resp
            elif '/tracker/ct_room_1' in url:
                return mock_detail_1_resp
            return MagicMock()
            
        mock_session.get.side_effect = mock_get
        
        # Pre-create room 2
        room_2 = TrackedRoom(
            room_id='room_2_uuid',
            hostname='archipelago.gg',
            cheese_tracker_id='ct_room_2'
        )
        self.session.add(room_2)
        self.session.flush()
        room_2_db_id = room_2.id
        
        # Create test user in DB
        encrypted_key = encrypt_api_key("fake_api_key")
        user = User(
            id=1,
            discord_username="test_discord_user",
            cheese_api_key=encrypted_key,
            cheese_user_id=12345,
            is_syncing_cheese=True,
            is_guest=False
        )
        self.session.add(user)
        self.session.flush()
        user_db_id = user.id
        
        # Pre-subscribe user to room 2
        sub_2 = UserRoomSubscription(
            user_id=user_db_id,
            room_id=room_2_db_id,
            alias='Deleted Room',
            is_archived=False
        )
        self.session.add(sub_2)
        self.session.commit()
        
        # Run setup_cheese_user_task
        setup_cheese_user_task(self.app, user_db_id)
        
        # Verify room 2's subscription was pruned/deleted
        fresh_session = Session()
        sub_check = fresh_session.query(UserRoomSubscription).filter_by(user_id=user_db_id, room_id=room_2_db_id).first()
        self.assertIsNone(sub_check)
        fresh_session.close()

if __name__ == '__main__':
    unittest.main()
