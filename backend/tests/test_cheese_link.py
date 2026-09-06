"""
Tests for who owns a user's room library.

The invariant: the app owns which rooms are in the list, Cheese Tracker owns
slot claims. A sync therefore reconciles claims for rooms the user linked and
flags linked rooms that fall off the dashboard, but it never creates a room and
never removes one. Rooms arrive from Cheese only when the user accepts a
suggestion, and leave only when the user says so. See #323.
"""
import json
import os
import unittest
from unittest.mock import patch, MagicMock

# Set up test DB and config before importing the app
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_cheese_link.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='  # Valid Fernet key

# Import through `app.*` only, never `backend.app.*` -- see the note in
# test_slot_track_mode.py. The two resolve to separate module objects with
# separate engines over the same SQLite file.
from app import create_app, Session, engine
from app.models import (
    Base, User, TrackedRoom, UserRoomSubscription, UserTrackedSlot, CheeseDismissedTracker
)
from app.api_cheese import setup_cheese_user_task
from app import api_cheese
from app.routes import rooms_routes
from app.encryption import encrypt_api_key
from app.utils import (
    TRACK_MODE_PLAY, TRACK_MODE_WATCH, CHEESE_LINK_LINKED, CHEESE_LINK_NONE
)

MY_CT_ID = 12345


def _remove_test_db():
    for suffix in ('', '-wal', '-shm'):
        path = f"{TEST_DB_PATH}{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def _run_inline(target=None, args=(), **kwargs):
    """Stands in for threading.Thread so background pushes run inline."""
    thread = MagicMock()
    thread.start.side_effect = lambda: target(*args)
    return thread


def _verified_room(coro):
    """
    Stands in for asyncio.run around the add-room server check.

    Closes the coroutine it was handed rather than dropping it, which is the
    difference between a clean test run and a "was never awaited" warning.
    """
    coro.close()
    return {
        'room_id': 'added_uuid',
        'hostname': 'archipelago.gg',
        'cached_full_address': 'archipelago.gg:12345',
        'cached_players_json': '[]',
        'cached_total_slots': 0,
        'ap_tracker_id': 'ap_trk',
    }


def _call(view, *args, body=None):
    """
    Invoke a route past its @handle_db_errors / @log_api_call / @token_required
    decorators, the way the other route tests in this suite do.
    """
    fn = view.__wrapped__.__wrapped__.__wrapped__
    with _app_ref[0].test_request_context(json=body or {}):
        return fn(*args)


_app_ref = [None]


class CheeseLinkTestBase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        _app_ref[0] = self.app
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

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        _remove_test_db()

    def make_user(self, **kwargs):
        defaults = dict(
            id=1,
            discord_username="me",
            cheese_api_key=encrypt_api_key("fake_api_key"),
            cheese_user_id=MY_CT_ID,
            is_guest=False,
        )
        defaults.update(kwargs)
        user = User(**defaults)
        self.session.add(user)
        self.session.commit()
        return user

    def mock_cheese(self, mock_session_cls, dashboard, details=None):
        """Wire up /user/self, /dashboard/tracker and /tracker/<id>."""
        details = details or {}
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session

        me_resp = MagicMock(ok=True)
        me_resp.json.return_value = {'id': MY_CT_ID, 'discord_username': 'me'}

        dash_resp = MagicMock(ok=True)
        dash_resp.json.return_value = dashboard

        def mock_get(url, *args, **kwargs):
            if '/user/self' in url:
                return me_resp
            if '/dashboard/tracker' in url:
                return dash_resp
            for ct_id, payload in details.items():
                if f'/tracker/{ct_id}' in url:
                    resp = MagicMock(ok=True)
                    resp.json.return_value = payload
                    return resp
            return MagicMock(ok=False, status_code=404)

        mock_session.get.side_effect = mock_get
        return mock_session


class TestSyncNeverChangesTheLibrary(CheeseLinkTestBase):

    @patch('app.api_cheese.requests.Session')
    def test_dashboard_tracker_the_app_does_not_have_is_not_imported(self, mock_session_cls):
        self.mock_cheese(
            mock_session_cls,
            dashboard=[{
                'tracker_id': 'ct_new',
                'room_link': 'https://archipelago.gg/room/brand_new_uuid',
                'title': 'Someone Added Me',
                'dashboard_override_visibility': True,
            }],
            details={'ct_new': {'games': [
                {'id': 1, 'position': 1, 'claimed_by_ct_user_id': MY_CT_ID}
            ]}},
        )
        user_id = self.make_user(is_syncing_cheese=True).id

        setup_cheese_user_task(self.app, user_id)

        fresh = Session()
        try:
            self.assertIsNone(
                fresh.query(TrackedRoom).filter_by(cheese_tracker_id='ct_new').first(),
                "a sync must not create rooms; the user accepts a suggestion instead",
            )
            self.assertEqual(fresh.query(UserRoomSubscription).count(), 0)
        finally:
            fresh.close()

    @patch('app.api_cheese.requests.Session')
    def test_empty_dashboard_changes_nothing(self, mock_session_cls):
        """
        One thin dashboard response used to delete a whole library. Absence of
        trackers is not evidence of anything.
        """
        self.mock_cheese(mock_session_cls, dashboard=[])
        user_id = self.make_user(is_syncing_cheese=True).id

        room = TrackedRoom(room_id="room_uuid", cheese_tracker_id="ct_room_1")
        self.session.add(room)
        self.session.flush()
        self.session.add(UserRoomSubscription(
            user_id=user_id, room_id=room.id, alias="Mine",
            cheese_link=CHEESE_LINK_LINKED
        ))
        self.session.add(UserTrackedSlot(
            user_id=user_id, room_id=room.id, slot_id=1, track_mode=TRACK_MODE_PLAY
        ))
        self.session.commit()
        room_id = room.id

        setup_cheese_user_task(self.app, user_id)

        fresh = Session()
        try:
            sub = fresh.query(UserRoomSubscription).filter_by(
                user_id=user_id, room_id=room_id
            ).first()
            slot = fresh.query(UserTrackedSlot).filter_by(
                user_id=user_id, room_id=room_id, slot_id=1
            ).first()
        finally:
            fresh.close()

        self.assertIsNotNone(sub)
        self.assertIsNone(sub.cheese_unlisted_at, "an empty dashboard flags nothing")
        self.assertEqual(slot.track_mode, TRACK_MODE_PLAY)

    @patch('app.api_cheese.requests.Session')
    def test_relisted_room_clears_the_flag(self, mock_session_cls):
        self.mock_cheese(
            mock_session_cls,
            dashboard=[{'tracker_id': 'ct_room_1', 'title': 'Back', 'room_link': None}],
            details={'ct_room_1': {'games': [
                {'id': 1, 'position': 1, 'claimed_by_ct_user_id': MY_CT_ID}
            ]}},
        )
        user_id = self.make_user(is_syncing_cheese=True).id

        room = TrackedRoom(room_id="room_uuid", cheese_tracker_id="ct_room_1")
        self.session.add(room)
        self.session.flush()
        from datetime import datetime
        self.session.add(UserRoomSubscription(
            user_id=user_id, room_id=room.id, alias="Back",
            cheese_link=CHEESE_LINK_LINKED, cheese_unlisted_at=datetime(2026, 1, 1)
        ))
        self.session.commit()
        room_id = room.id

        setup_cheese_user_task(self.app, user_id)

        fresh = Session()
        try:
            sub = fresh.query(UserRoomSubscription).filter_by(
                user_id=user_id, room_id=room_id
            ).first()
        finally:
            fresh.close()
        self.assertIsNone(sub.cheese_unlisted_at)


    @patch('app.api_cheese.requests.Session')
    def test_a_hidden_tracker_is_not_treated_as_removed(self, mock_session_cls):
        """
        Hiding a room on the Cheese dashboard is not removing it. The tracker is
        still listed, just flagged hidden, so the room keeps reconciling and is
        never marked unlisted.
        """
        self.mock_cheese(
            mock_session_cls,
            dashboard=[{
                'tracker_id': 'ct_room_1',
                'title': 'Hidden On Cheese',
                'room_link': 'https://archipelago.gg/room/room_uuid',
                'dashboard_override_visibility': False,
            }],
            details={'ct_room_1': {'games': [
                {'id': 1, 'position': 1, 'claimed_by_ct_user_id': MY_CT_ID}
            ]}},
        )
        user_id = self.make_user(is_syncing_cheese=True).id

        room = TrackedRoom(room_id="room_uuid", cheese_tracker_id="ct_room_1")
        self.session.add(room)
        self.session.flush()
        self.session.add(UserRoomSubscription(
            user_id=user_id, room_id=room.id, alias="Hidden",
            cheese_link=CHEESE_LINK_LINKED
        ))
        self.session.commit()
        room_id = room.id

        setup_cheese_user_task(self.app, user_id)

        fresh = Session()
        try:
            sub = fresh.query(UserRoomSubscription).filter_by(
                user_id=user_id, room_id=room_id
            ).first()
            slot = fresh.query(UserTrackedSlot).filter_by(
                user_id=user_id, room_id=room_id, slot_id=1
            ).first()
        finally:
            fresh.close()

        self.assertIsNotNone(sub)
        self.assertIsNone(sub.cheese_unlisted_at, "hidden is not the same as gone")
        self.assertIsNotNone(slot, "and its claims are still reconciled")


class TestDisconnectKeepsEverything(CheeseLinkTestBase):
    """
    Disconnecting takes Cheese out of the interface, not out of the library.

    Nothing stored is destroyed, so reconnecting restores the previous state
    rather than a guess at it. The app hides every Cheese affordance by keying it
    off the connection instead.
    """

    def _connected_user_with_a_linked_room(self):
        user = self.make_user()
        room = TrackedRoom(room_id="room_uuid", cheese_tracker_id="ct_room_1")
        self.session.add(room)
        self.session.flush()
        self.session.add(UserRoomSubscription(
            user_id=user.id, room_id=room.id, alias="Mine",
            cheese_link=CHEESE_LINK_LINKED
        ))
        self.session.add(UserTrackedSlot(
            user_id=user.id, room_id=room.id, slot_id=1, track_mode=TRACK_MODE_WATCH
        ))
        self.session.commit()
        return user, room.id

    def test_disconnect_clears_the_credentials_and_nothing_else(self):
        user, room_id = self._connected_user_with_a_linked_room()
        user_id = user.id

        _call(api_cheese.disconnect_cheese_account, user)

        fresh = Session()
        try:
            updated = fresh.query(User).get(user_id)
            self.assertIsNone(updated.cheese_api_key)
            self.assertIsNone(updated.cheese_user_id)
            self.assertFalse(updated.is_syncing_cheese)

            sub = fresh.query(UserRoomSubscription).filter_by(
                user_id=user_id, room_id=room_id
            ).first()
            self.assertIsNotNone(sub, "the room stays in the library")
            self.assertEqual(
                sub.cheese_link, CHEESE_LINK_LINKED,
                "and keeps its link, so reconnecting restores it",
            )

            slot = fresh.query(UserTrackedSlot).filter_by(
                user_id=user_id, room_id=room_id, slot_id=1
            ).first()
            self.assertIsNotNone(slot)
            self.assertEqual(
                slot.track_mode, TRACK_MODE_WATCH,
                "watch mode survives; the app just stops drawing the eye",
            )

            room = fresh.query(TrackedRoom).get(room_id)
            self.assertEqual(
                room.cheese_tracker_id, 'ct_room_1',
                "the tracker id is shared with everyone else tracking this room",
            )
        finally:
            fresh.close()

    def test_a_disconnected_user_is_invisible_to_the_poller(self):
        """
        Clearing cheese_user_id is load-bearing, not cosmetic: it is what makes
        process_cheese_update skip this user, so a poll cannot go on demoting the
        slots of somebody who has left.
        """
        user, _ = self._connected_user_with_a_linked_room()
        user_id = user.id

        _call(api_cheese.disconnect_cheese_account, user)

        fresh = Session()
        try:
            self.assertIsNone(fresh.query(User).get(user_id).cheese_user_id)
        finally:
            fresh.close()


class TestSuggestions(CheeseLinkTestBase):
    """Cheese proposes rooms; it never writes them into a library."""

    def _dashboard(self):
        return [
            {'tracker_id': 'ct_known', 'title': 'Already Mine',
             'room_link': 'https://archipelago.gg/room/known_uuid',
             'dashboard_override_visibility': True},
            {'tracker_id': 'ct_new', 'title': 'New One',
             'room_link': 'https://archipelago.gg/room/new_uuid',
             'dashboard_override_visibility': True},
            {'tracker_id': 'ct_dismissed', 'title': 'No Thanks',
             'room_link': 'https://archipelago.gg/room/dismissed_uuid',
             'dashboard_override_visibility': True},
            {'tracker_id': 'ct_hidden', 'title': 'Hidden On Cheese',
             'room_link': 'https://archipelago.gg/room/hidden_uuid',
             'dashboard_override_visibility': False},
        ]

    def _seed(self):
        user = self.make_user()
        known = TrackedRoom(room_id="known_uuid", cheese_tracker_id="ct_known")
        self.session.add(known)
        self.session.flush()
        self.session.add(UserRoomSubscription(
            user_id=user.id, room_id=known.id, alias="Already Mine",
            cheese_link=CHEESE_LINK_LINKED
        ))
        self.session.add(CheeseDismissedTracker(
            user_id=user.id, cheese_tracker_id='ct_dismissed'
        ))
        self.session.commit()
        return user

    @patch('app.api_cheese._fetch_dashboard')
    def test_available_lists_only_new_visible_undismissed_trackers(self, mock_dash):
        mock_dash.return_value = self._dashboard()
        user = self._seed()

        resp = _call(api_cheese.list_available_cheese_rooms, user)
        payload = json.loads(resp.get_data(as_text=True))

        self.assertEqual(payload['count'], 1)
        self.assertEqual(payload['available'][0]['cheese_tracker_id'], 'ct_new')

    @patch('app.api_cheese._fetch_dashboard')
    def test_dismissing_a_tracker_stops_it_being_offered(self, mock_dash):
        mock_dash.return_value = self._dashboard()
        user = self._seed()

        _call(api_cheese.dismiss_available_cheese_rooms, user,
              body={'cheese_tracker_ids': ['ct_new']})

        resp = _call(api_cheese.list_available_cheese_rooms, user)
        payload = json.loads(resp.get_data(as_text=True))
        self.assertEqual(payload['count'], 0)

    @patch('app.api_cheese._fetch_tracker_details')
    @patch('app.api_cheese.requests.Session')
    @patch('app.api_cheese._fetch_dashboard')
    def test_importing_creates_a_linked_room_and_syncs_its_claims(
        self, mock_dash, mock_session_cls, mock_details
    ):
        mock_dash.return_value = self._dashboard()
        mock_details.return_value = {'ct_new': {
            'updated_at': '2026-06-23T10:00:00Z',
            'games': [{'id': 5, 'position': 3, 'claimed_by_ct_user_id': MY_CT_ID}],
        }}
        user = self._seed()
        user_id = user.id

        resp = _call(api_cheese.import_available_cheese_rooms, user,
                     body={'cheese_tracker_ids': ['ct_new']})
        payload = json.loads(resp.get_data(as_text=True))
        self.assertEqual(payload['imported'], 1)

        fresh = Session()
        try:
            room = fresh.query(TrackedRoom).filter_by(cheese_tracker_id='ct_new').first()
            self.assertIsNotNone(room)
            self.assertEqual(room.room_id, 'new_uuid')

            sub = fresh.query(UserRoomSubscription).filter_by(
                user_id=user_id, room_id=room.id
            ).first()
            self.assertIsNotNone(sub)
            self.assertEqual(sub.cheese_link, CHEESE_LINK_LINKED)
            self.assertEqual(sub.alias, 'New One')

            slot = fresh.query(UserTrackedSlot).filter_by(
                user_id=user_id, room_id=room.id, slot_id=3
            ).first()
            self.assertIsNotNone(slot, "the slot Cheese says is theirs comes with it")
            self.assertEqual(slot.track_mode, TRACK_MODE_PLAY)
        finally:
            fresh.close()

    @patch('app.api_cheese._fetch_tracker_details')
    @patch('app.api_cheese.requests.Session')
    @patch('app.api_cheese._fetch_dashboard')
    def test_importing_a_dismissed_tracker_clears_the_dismissal(
        self, mock_dash, mock_session_cls, mock_details
    ):
        mock_dash.return_value = self._dashboard()
        mock_details.return_value = {'ct_dismissed': {'games': []}}
        user = self._seed()
        user_id = user.id

        _call(api_cheese.import_available_cheese_rooms, user,
              body={'cheese_tracker_ids': ['ct_dismissed']})

        fresh = Session()
        try:
            remaining = fresh.query(CheeseDismissedTracker).filter_by(
                user_id=user_id, cheese_tracker_id='ct_dismissed'
            ).count()
        finally:
            fresh.close()
        self.assertEqual(remaining, 0)


class TestPublishingIsOptIn(CheeseLinkTestBase):
    """
    Publishing creates a public tracker on someone else's service under the
    user's account, so it is a per-room decision rather than a global mode.
    """

    def _add_room(self, user, sync_to_cheese=None):
        body = {
            'room_url': 'https://archipelago.gg/room/added_uuid',
            'alias': 'Added Room',
        }
        if sync_to_cheese is not None:
            body['sync_to_cheese'] = sync_to_cheese
        return _call(rooms_routes.add_room, user, body=body)

    @patch('app.api_cheese.push_new_room_to_cheese')
    @patch('app.routes.rooms_routes.asyncio.run')
    def test_opting_out_stores_no_link_and_pushes_nothing(self, mock_run, mock_push):
        mock_run.side_effect = _verified_room
        user = self.make_user()
        user_id = user.id

        self._add_room(user, sync_to_cheese=False)

        fresh = Session()
        try:
            sub = fresh.query(UserRoomSubscription).filter_by(user_id=user_id).first()
        finally:
            fresh.close()

        self.assertIsNotNone(sub)
        self.assertEqual(sub.cheese_link, CHEESE_LINK_NONE)
        mock_push.assert_not_called()

    @patch('threading.Thread', side_effect=_run_inline)
    @patch('app.api_cheese.push_new_room_to_cheese')
    @patch('app.routes.rooms_routes.asyncio.run')
    def test_opting_in_links_the_room_and_pushes_it(self, mock_run, mock_push, mock_thread):
        mock_run.side_effect = _verified_room
        user = self.make_user()
        user_id = user.id

        self._add_room(user, sync_to_cheese=True)

        fresh = Session()
        try:
            sub = fresh.query(UserRoomSubscription).filter_by(user_id=user_id).first()
        finally:
            fresh.close()

        self.assertEqual(sub.cheese_link, CHEESE_LINK_LINKED)
        mock_push.assert_called_once()

    @patch('threading.Thread', side_effect=_run_inline)
    @patch('app.api_cheese.push_new_room_to_cheese')
    @patch('app.routes.rooms_routes.asyncio.run')
    def test_an_older_client_gets_the_users_default(self, mock_run, mock_push, mock_thread):
        """A build that sends no sync_to_cheese keeps the behaviour it had."""
        mock_run.side_effect = _verified_room
        user = self.make_user(cheese_publish_new_rooms=False)
        user_id = user.id

        self._add_room(user)

        fresh = Session()
        try:
            sub = fresh.query(UserRoomSubscription).filter_by(user_id=user_id).first()
        finally:
            fresh.close()

        self.assertEqual(sub.cheese_link, CHEESE_LINK_NONE)
        mock_push.assert_not_called()


class TestLinkToggle(CheeseLinkTestBase):

    def _room_for(self, user_id, link=CHEESE_LINK_NONE, tracker_id=None):
        room = TrackedRoom(
            room_id="room_uuid",
            hostname="archipelago.gg",
            tracker_id="ap_trk",
            cheese_tracker_id=tracker_id,
        )
        self.session.add(room)
        self.session.flush()
        self.session.add(UserRoomSubscription(
            user_id=user_id, room_id=room.id, alias="Room", cheese_link=link
        ))
        self.session.commit()
        return room.id

    @patch('threading.Thread', side_effect=_run_inline)
    @patch('app.api_cheese.push_new_room_to_cheese')
    def test_linking_an_unpushed_room_pushes_it(self, mock_push, mock_thread):
        user = self.make_user()
        room_id = self._room_for(user.id)

        resp = _call(rooms_routes.update_cheese_link, user, room_id, body={'linked': True})
        payload = json.loads(resp.get_data(as_text=True))

        self.assertEqual(payload['cheese_link'], CHEESE_LINK_LINKED)
        self.assertTrue(payload['pushing'])
        mock_push.assert_called_once()

    @patch('threading.Thread', side_effect=_run_inline)
    @patch('app.api_cheese.push_new_room_to_cheese')
    def test_unlinking_keeps_the_room_and_its_tracker(self, mock_push, mock_thread):
        user = self.make_user()
        user_id = user.id
        room_id = self._room_for(user_id, link=CHEESE_LINK_LINKED, tracker_id='ct_room_1')

        _call(rooms_routes.update_cheese_link, user, room_id, body={'linked': False})

        fresh = Session()
        try:
            sub = fresh.query(UserRoomSubscription).filter_by(
                user_id=user_id, room_id=room_id
            ).first()
            room = fresh.query(TrackedRoom).get(room_id)
        finally:
            fresh.close()

        self.assertIsNotNone(sub, "unlinking never removes the room")
        self.assertEqual(sub.cheese_link, CHEESE_LINK_NONE)
        self.assertEqual(room.cheese_tracker_id, 'ct_room_1',
                         "the Cheese tracker itself is left alone")
        mock_push.assert_not_called()

    def test_unlinked_room_is_not_written_to(self):
        """
        A room keeps its tracker id after unlinking, so the id alone must not be
        taken as permission to write to Cheese.
        """
        user = self.make_user()
        user_id = user.id
        room_id = self._room_for(user_id, link=CHEESE_LINK_NONE, tracker_id='ct_room_1')

        with patch('app.api_cheese._background_push_worker') as mock_worker:
            api_cheese.push_slot_changes_to_cheese(self.app, user_id, room_id, {1}, set())

        mock_worker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
