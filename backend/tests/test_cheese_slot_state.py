import os
import json
import unittest
from unittest.mock import patch, MagicMock

# Set up test DB and config before importing the app
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_ap_tracker_slot.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='  # Valid Fernet key

from backend.app import create_app, Session, engine
from backend.app.models import Base, User, TrackedRoom, UserRoomSubscription, UserTrackedSlot
from backend.app.api_cheese import apply_cheese_slot_update, refresh_tracker_cache, _background_push_worker
from backend.app.routes.slots_routes import game_is_owned_by, build_cheese_slot_state
from backend.app.encryption import encrypt_api_key

MY_CT_ID = 12345
OTHER_CT_ID = 99999


def make_game(**overrides):
    game = {
        'id': 99,
        'position': 1,
        'name': 'MyGame',
        'game': 'A Link to the Past',
        'notes': 'old notes',
        'progression_status': 'unknown',
        'completion_status': 'incomplete',
        'discord_ping': 'never',
        'last_checked': None,
        'last_activity': '2026-08-01T00:00:00Z',
        'claimed_by_ct_user_id': MY_CT_ID,
        'discord_username': None,
        'availability_status': 'claimed',
        'checks_done': 5,
        'checks_total': 10,
    }
    game.update(overrides)
    return game


def make_tracker(game, global_ping_policy=None):
    return {
        'tracker_id': 'ct_room_1',
        'updated_at': '2026-08-02T00:00:00Z',
        'global_ping_policy': global_ping_policy,
        'games': [game],
    }


class TestCheeseSlotPureHelpers(unittest.TestCase):
    def test_owned_by_authenticated_match(self):
        game = make_game(claimed_by_ct_user_id=MY_CT_ID)
        self.assertTrue(game_is_owned_by(game, MY_CT_ID, None))
        self.assertFalse(game_is_owned_by(game, OTHER_CT_ID, None))

    def test_owned_by_unauthenticated_discord_match(self):
        game = make_game(claimed_by_ct_user_id=None, discord_username='Cooldude')
        self.assertTrue(game_is_owned_by(game, None, 'cooldude'))
        self.assertFalse(game_is_owned_by(game, None, 'someoneelse'))

    def test_unclaimed_is_not_owned(self):
        game = make_game(claimed_by_ct_user_id=None, discord_username=None)
        self.assertFalse(game_is_owned_by(game, MY_CT_ID, 'cooldude'))

    def test_build_slot_state_shape(self):
        game = make_game(notes='hello', progression_status='bk')
        state = build_cheese_slot_state(game, 'sparingly', MY_CT_ID, None)
        self.assertEqual(state['game_id'], 99)
        self.assertEqual(state['notes'], 'hello')
        self.assertEqual(state['progression_status'], 'bk')
        self.assertEqual(state['global_ping_policy'], 'sparingly')
        self.assertTrue(state['is_mine'])


class TestApplyCheeseSlotUpdate(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app_context = self.app.app_context()
        self.app_context.push()

        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.session = Session()

        user = User(
            id=1,
            discord_username='Cooldude',
            cheese_api_key=encrypt_api_key('secret-key'),
            cheese_user_id=MY_CT_ID,
            is_guest=False,
        )
        room = TrackedRoom(
            id=10,
            room_id='room_uuid',
            cheese_tracker_id='ct_room_1',
            cached_cheese_json=json.dumps(make_tracker(make_game())),
        )
        sub = UserRoomSubscription(user_id=1, room_id=10, alias='Test Room')
        slot = UserTrackedSlot(user_id=1, room_id=10, slot_id=1)
        self.session.add_all([user, room, sub, slot])
        self.session.commit()

    def tearDown(self):
        self.session.close()
        Session.remove()
        engine.dispose()
        self.app_context.pop()
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def _mock_get(self, tracker):
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = tracker
        return resp

    def _mock_put(self, status_code=200, body=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.content = b'{}' if body is not None else b''
        resp.json.return_value = body if body is not None else {}
        resp.text = ''
        return resp

    @patch('backend.app.api_cheese._cheese_session.put')
    @patch('backend.app.api_cheese._cheese_session.get')
    def test_notes_update_merges_and_persists(self, mock_get, mock_put):
        mock_get.return_value = self._mock_get(make_tracker(make_game()))
        # Server echoes the updated game with new notes.
        mock_put.return_value = self._mock_put(body=make_game(notes='new notes'))

        result = apply_cheese_slot_update(self.app, 1, 10, 1, {'notes': 'new notes'})

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['game']['notes'], 'new notes')
        # PUT payload carried the merged notes.
        sent_payload = mock_put.call_args.kwargs['json']
        self.assertEqual(sent_payload['notes'], 'new notes')
        # Cache was spliced.
        room = self.session.query(TrackedRoom).get(10)
        self.session.refresh(room)
        cached = json.loads(room.cached_cheese_json)
        self.assertEqual(cached['games'][0]['notes'], 'new notes')

    @patch('backend.app.api_cheese._cheese_session.put')
    @patch('backend.app.api_cheese._cheese_session.get')
    def test_bk_stamps_last_checked(self, mock_get, mock_put):
        mock_get.return_value = self._mock_get(make_tracker(make_game()))
        mock_put.return_value = self._mock_put(body=make_game(progression_status='bk'))

        result = apply_cheese_slot_update(self.app, 1, 10, 1, {'progression_status': 'bk'})

        self.assertEqual(result['status'], 'ok')
        sent_payload = mock_put.call_args.kwargs['json']
        self.assertEqual(sent_payload['progression_status'], 'bk')
        self.assertIsNotNone(sent_payload['last_checked'])

    @patch('backend.app.api_cheese._cheese_session.put')
    @patch('backend.app.api_cheese._cheese_session.get')
    def test_still_bk_touches_last_checked_only(self, mock_get, mock_put):
        mock_get.return_value = self._mock_get(make_tracker(make_game(progression_status='bk')))
        mock_put.return_value = self._mock_put(body=make_game(progression_status='bk'))

        result = apply_cheese_slot_update(self.app, 1, 10, 1, {'touch_last_checked': True})

        self.assertEqual(result['status'], 'ok')
        sent_payload = mock_put.call_args.kwargs['json']
        self.assertIsNotNone(sent_payload['last_checked'])
        self.assertEqual(sent_payload['progression_status'], 'bk')

    @patch('backend.app.api_cheese._cheese_session.put')
    @patch('backend.app.api_cheese._cheese_session.get')
    def test_completion_force_upgrade_uses_server_response(self, mock_get, mock_put):
        mock_get.return_value = self._mock_get(make_tracker(make_game()))
        # We ask for 'incomplete' but the server force-upgrades to 'all_checks'.
        mock_put.return_value = self._mock_put(body=make_game(completion_status='all_checks'))

        result = apply_cheese_slot_update(self.app, 1, 10, 1, {'completion_status': 'incomplete'})

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['game']['completion_status'], 'all_checks')

    @patch('backend.app.api_cheese._cheese_session.put')
    @patch('backend.app.api_cheese._cheese_session.get')
    def test_ownership_rejected_for_other_users_slot(self, mock_get, mock_put):
        mock_get.return_value = self._mock_get(
            make_tracker(make_game(claimed_by_ct_user_id=OTHER_CT_ID))
        )

        result = apply_cheese_slot_update(self.app, 1, 10, 1, {'notes': 'hax'})

        self.assertEqual(result['status'], 'forbidden')
        mock_put.assert_not_called()

    @patch('backend.app.api_cheese._cheese_session.put')
    @patch('backend.app.api_cheese._cheese_session.get')
    def test_precondition_failed_maps_to_conflict(self, mock_get, mock_put):
        mock_get.return_value = self._mock_get(make_tracker(make_game()))
        mock_put.return_value = self._mock_put(status_code=412)

        result = apply_cheese_slot_update(self.app, 1, 10, 1, {'notes': 'race'})

        self.assertEqual(result['status'], 'conflict')

    @patch('backend.app.api_cheese._cheese_session.put')
    @patch('backend.app.api_cheese._cheese_session.get')
    def test_slot_not_present_on_tracker(self, mock_get, mock_put):
        mock_get.return_value = self._mock_get(make_tracker(make_game(position=2)))

        result = apply_cheese_slot_update(self.app, 1, 10, 1, {'notes': 'x'})

        self.assertEqual(result['status'], 'not_found')
        mock_put.assert_not_called()


class TestRefreshTrackerCache(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app_context = self.app.app_context()
        self.app_context.push()

        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.session = Session()

        user = User(
            id=1,
            discord_username='Cooldude',
            cheese_api_key=encrypt_api_key('secret-key'),
            cheese_user_id=MY_CT_ID,
            is_guest=False,
        )
        room = TrackedRoom(id=10, room_id='room_uuid', cheese_tracker_id='ct_room_1')
        self.session.add_all([user, room])
        self.session.commit()

    def tearDown(self):
        self.session.close()
        Session.remove()
        engine.dispose()
        self.app_context.pop()
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def test_not_connected_when_no_key(self):
        user = self.session.query(User).get(1)
        user.cheese_api_key = None
        self.session.commit()
        result = refresh_tracker_cache(self.app, 1, 10)
        self.assertEqual(result['status'], 'not_connected')

    def test_no_tracker_when_room_unlinked(self):
        room = self.session.query(TrackedRoom).get(10)
        room.cheese_tracker_id = None
        self.session.commit()
        result = refresh_tracker_cache(self.app, 1, 10)
        self.assertEqual(result['status'], 'no_tracker')

    # Patched at the definition site: refresh_tracker_cache imports it inside the
    # function, and app.poller only re-exports it.
    @patch('app.services.cheese_service.process_cheese_update')
    @patch('backend.app.api_cheese._cheese_session.get')
    def test_ok_invokes_processing(self, mock_get, mock_process):
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = make_tracker(make_game())
        mock_get.return_value = resp

        result = refresh_tracker_cache(self.app, 1, 10)

        self.assertEqual(result['status'], 'ok')
        mock_process.assert_called_once()
        # Called with (room_db_id, tracker_data, remote_updated_at)
        args = mock_process.call_args.args
        self.assertEqual(args[0], 10)
        self.assertEqual(args[2], '2026-08-02T00:00:00Z')

    @patch('backend.app.api_cheese._cheese_session.get')
    def test_fetch_failure_returns_error(self, mock_get):
        resp = MagicMock()
        resp.ok = False
        resp.status_code = 500
        mock_get.return_value = resp
        result = refresh_tracker_cache(self.app, 1, 10)
        self.assertEqual(result['status'], 'error')


if __name__ == '__main__':
    unittest.main()


class TestBackgroundPushFetchesTrackerOnce(unittest.TestCase):
    """
    The tracker fetch used to sit inside send_state, so pushing N slots downloaded the
    whole tracker N times -- N chances to hit the read timeout that drops a claim
    silently, which is why large rooms were worst affected. See #304.
    """

    def setUp(self):
        self.app = create_app()
        self.app_context = self.app.app_context()
        self.app_context.push()

        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.session = Session()

        user = User(
            id=1,
            discord_username='Cooldude',
            cheese_api_key=encrypt_api_key('secret-key'),
            cheese_user_id=MY_CT_ID,
            is_guest=False,
        )
        room = TrackedRoom(
            id=10,
            room_id='room_uuid',
            cheese_tracker_id='ct_room_1',
            cached_players_json='[]',
        )
        sub = UserRoomSubscription(user_id=1, room_id=10, alias='Test Room')
        self.session.add_all([user, room, sub])
        self.session.add_all([
            UserTrackedSlot(user_id=1, room_id=10, slot_id=pos) for pos in (1, 2, 3)
        ])
        self.session.commit()

    def tearDown(self):
        self.session.close()
        Session.remove()
        engine.dispose()
        self.app_context.pop()
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    @patch('backend.app.api_cheese._cheese_session.put')
    @patch('backend.app.api_cheese._cheese_session.get')
    def test_three_slots_cost_one_tracker_fetch(self, mock_get, mock_put):
        tracker = {
            'tracker_id': 'ct_room_1',
            'updated_at': '2026-08-02T00:00:00Z',
            'global_ping_policy': None,
            'games': [make_game(id=90 + pos, position=pos) for pos in (1, 2, 3)],
        }
        get_resp = MagicMock()
        get_resp.ok = True
        get_resp.json.return_value = tracker
        mock_get.return_value = get_resp

        put_resp = MagicMock()
        put_resp.status_code = 200
        put_resp.content = b'{}'
        put_resp.json.return_value = {}
        put_resp.text = ''
        mock_put.return_value = put_resp

        _background_push_worker(self.app, 1, 'ct_room_1', [1, 2, 3], [], MY_CT_ID, {})

        self.assertEqual(mock_get.call_count, 1, "the tracker should be fetched once for the whole batch")
        self.assertEqual(mock_put.call_count, 3, "each slot should still be written individually")

    @patch('backend.app.api_cheese._cheese_session.put')
    @patch('backend.app.api_cheese._cheese_session.get')
    def test_unreadable_tracker_pushes_nothing(self, mock_get, mock_put):
        get_resp = MagicMock()
        get_resp.ok = False
        get_resp.status_code = 503
        mock_get.return_value = get_resp

        _background_push_worker(self.app, 1, 'ct_room_1', [1, 2, 3], [], MY_CT_ID, {})

        # Without a snapshot there is nothing to build a precondition from, so the
        # batch aborts rather than writing blind.
        mock_put.assert_not_called()
