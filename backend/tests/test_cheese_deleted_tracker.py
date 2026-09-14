"""A tracker deleted on Cheese stops holding its room (#352).

Nothing used to clear a dead cheese_tracker_id. The Cheese poll collapsed every
failure to "no data" and returned, so a deleted tracker was polled forever, and
because a room holds one tracker id, the replacement tracker for the same room
was refused by the import and hidden from suggestions as belonging to another
tracker -- one that no longer existed.

Two things matter as much as the unlink itself:

- Only Cheese saying "not found" may unlink. A timeout, a 5xx, a 429 or a 404
  from something in front of Cheese must leave every link alone, or an outage
  unlinks every library at once.
- Linked subscriptions go to 'none' with the id. The sync's healing phase pushes
  a linked room with no tracker id to Cheese as a new tracker, so clearing the id
  alone would recreate the tracker the user deleted.
"""
import asyncio
import json
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_cheese_deleted_tracker.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

from multidict import CIMultiDict

from app import create_app, Session, engine
from app import api_cheese
from app import poller
from app.api_cheese import setup_cheese_user_task
from app.encryption import encrypt_api_key
from app.models import Base, TrackedRoom, User, UserRoomSubscription
from app.services.cheese_service import unlink_deleted_tracker
from app.utils import CHEESE_LINK_LINKED, CHEESE_LINK_NONE

MY_CT_ID = 12345
SHARED_ROOM = "shared_uuid"


def _remove_test_db():
    for suffix in ('', '-wal', '-shm'):
        path = f"{TEST_DB_PATH}{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


_app_ref = [None]


def _call(view, *args, body=None):
    """Invoke a route past its three decorators, as test_cheese_link.py does."""
    fn = view.__wrapped__.__wrapped__.__wrapped__
    with _app_ref[0].test_request_context(json=body or {}):
        return fn(*args)


class DeletedTrackerTestBase(unittest.TestCase):
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

    def _user(self, user_id=1, discord="me"):
        user = User(
            id=user_id, discord_username=discord, is_guest=False,
            cheese_api_key=encrypt_api_key("fake_api_key"), cheese_user_id=MY_CT_ID,
        )
        self.session.add(user)
        self.session.flush()
        return user

    def _room_on_dead_tracker(self):
        """A real room linked by one user and tracked privately by another."""
        linked_user = self._user(1, "me")
        private_user = self._user(2, "other")
        room = TrackedRoom(
            room_id=SHARED_ROOM, hostname="archipelago.gg", tracker_id="ap_trk",
            cheese_tracker_id="ct_dead",
            cached_cheese_json=json.dumps({'from': 'ct_dead'}),
            cheese_updated_at=datetime(2026, 9, 1),
        )
        self.session.add(room)
        self.session.flush()
        self.session.add(UserRoomSubscription(
            user_id=linked_user.id, room_id=room.id, alias="Mine",
            cheese_link=CHEESE_LINK_LINKED, cheese_unlisted_at=datetime(2026, 9, 2),
        ))
        self.session.add(UserRoomSubscription(
            user_id=private_user.id, room_id=room.id, alias="Theirs",
            cheese_link=CHEESE_LINK_NONE,
        ))
        self.session.commit()
        return linked_user.id, private_user.id, room.id


class TestUnlinkDeletedTracker(DeletedTrackerTestBase):
    def test_the_room_lets_go_of_the_dead_tracker(self):
        linked_id, private_id, room_id = self._room_on_dead_tracker()

        self.assertTrue(unlink_deleted_tracker(room_id, "ct_dead"))

        fresh = Session()
        try:
            room = fresh.get(TrackedRoom, room_id)
            self.assertIsNone(room.cheese_tracker_id)
            self.assertIsNone(room.cached_cheese_json,
                              "the dead tracker's claims would still be served")
            self.assertIsNone(room.cheese_updated_at,
                              "a replacement's first poll would not be treated as a first sync")

            linked = fresh.get(UserRoomSubscription, (linked_id, room_id))
            self.assertEqual(linked.cheese_link, CHEESE_LINK_NONE)
            self.assertIsNone(linked.cheese_unlisted_at)
            self.assertEqual(fresh.get(UserRoomSubscription, (private_id, room_id)).alias, "Theirs")
        finally:
            fresh.close()

    def test_the_room_and_every_subscription_stay(self):
        """The app owns the library (#323). Losing a tracker is not losing a room."""
        _, _, room_id = self._room_on_dead_tracker()

        unlink_deleted_tracker(room_id, "ct_dead")

        fresh = Session()
        try:
            self.assertIsNotNone(fresh.get(TrackedRoom, room_id))
            self.assertEqual(fresh.query(UserRoomSubscription).filter_by(room_id=room_id).count(), 2)
        finally:
            fresh.close()

    def test_a_room_re_pointed_since_the_fetch_is_left_alone(self):
        """An import or a merge can move the room to another tracker between the
        poll's request and this write. The newer link must survive."""
        linked_id, _, room_id = self._room_on_dead_tracker()
        room = self.session.get(TrackedRoom, room_id)
        room.cheese_tracker_id = "ct_replacement"
        self.session.commit()

        self.assertFalse(unlink_deleted_tracker(room_id, "ct_dead"))

        fresh = Session()
        try:
            self.assertEqual(fresh.get(TrackedRoom, room_id).cheese_tracker_id, "ct_replacement")
            self.assertEqual(fresh.get(UserRoomSubscription, (linked_id, room_id)).cheese_link,
                             CHEESE_LINK_LINKED)
        finally:
            fresh.close()

    def test_a_room_that_is_gone_is_not_an_error(self):
        self.assertFalse(unlink_deleted_tracker(9999, "ct_dead"))


class TestWhatTheUnlinkMakesPossible(DeletedTrackerTestBase):
    @patch('app.api_cheese._fetch_tracker_details')
    @patch('app.api_cheese.requests.Session')
    @patch('app.api_cheese._fetch_dashboard')
    def test_the_replacement_tracker_can_be_imported(self, mock_dash, mock_session_cls, mock_details):
        """The user-visible failure in #352: after #351 the replacement was
        refused as belonging to another tracker, by every route."""
        mock_dash.return_value = [{
            'tracker_id': 'ct_replacement', 'title': 'Recreated',
            'room_link': f'https://archipelago.gg/room/{SHARED_ROOM}',
            'dashboard_override_visibility': True,
        }]
        mock_details.return_value = {'ct_replacement': {'games': []}}
        linked_id, _, room_id = self._room_on_dead_tracker()
        user = self.session.get(User, linked_id)

        blocked = json.loads(_call(api_cheese.import_available_cheese_rooms, user,
                                   body={'cheese_tracker_ids': ['ct_replacement']}).get_data(as_text=True))
        self.assertEqual(blocked['linked_elsewhere'], ['ct_replacement'],
                         "precondition: without the unlink the replacement is refused")

        unlink_deleted_tracker(room_id, "ct_dead")
        user = Session().get(User, linked_id)

        payload = json.loads(_call(api_cheese.import_available_cheese_rooms, user,
                                   body={'cheese_tracker_ids': ['ct_replacement']}).get_data(as_text=True))

        self.assertEqual(payload['linked_elsewhere'], [])
        self.assertEqual(payload['failed'], [])
        # 0, not 1: the user already has this room, so the import re-links their
        # subscription rather than adding one, and only additions are counted.
        self.assertEqual(payload['imported'], 0)
        fresh = Session()
        try:
            self.assertEqual(fresh.get(TrackedRoom, room_id).cheese_tracker_id, "ct_replacement")
            self.assertEqual(fresh.get(UserRoomSubscription, (linked_id, room_id)).cheese_link,
                             CHEESE_LINK_LINKED)
        finally:
            fresh.close()

    def _sync_with_dashboard(self, mock_session_cls, user_id):
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        me = MagicMock(ok=True)
        me.json.return_value = {'id': MY_CT_ID}
        dash = MagicMock(ok=True)
        dash.json.return_value = [{'tracker_id': 'ct_unrelated'}]
        mock_session.get.side_effect = lambda url, *a, **k: (
            me if '/user/self' in url else dash if '/dashboard/tracker' in url
            else MagicMock(ok=False, status_code=404))
        self.session.get(User, user_id).is_syncing_cheese = True
        self.session.commit()
        setup_cheese_user_task(self.app, user_id)

    @patch('app.api_cheese.push_new_room_to_cheese')
    @patch('app.api_cheese.requests.Session')
    def test_the_next_sync_does_not_recreate_the_deleted_tracker(self, mock_session_cls, mock_push):
        linked_id, _, room_id = self._room_on_dead_tracker()
        unlink_deleted_tracker(room_id, "ct_dead")

        self._sync_with_dashboard(mock_session_cls, linked_id)

        mock_push.assert_not_called()

    @patch('app.api_cheese.push_new_room_to_cheese')
    @patch('app.api_cheese.requests.Session')
    def test_clearing_only_the_id_would_recreate_it(self, mock_session_cls, mock_push):
        """The control for the test above, and the reason the link changes too."""
        linked_id, _, room_id = self._room_on_dead_tracker()
        room = self.session.get(TrackedRoom, room_id)
        room.cheese_tracker_id = None
        self.session.commit()

        self._sync_with_dashboard(mock_session_cls, linked_id)

        mock_push.assert_called_once()


def _run_poll(fetch_result):
    """Run run_cheese_poll once against a canned fetch result."""
    unlink = MagicMock(return_value=True)
    process = MagicMock(return_value={})
    room_info = {'db_id': 7, 'cheese_tracker_id': 'ct_dead', 'cheese_updated_at': None}

    async def go():
        await poller.run_cheese_poll(room_info, asyncio.get_running_loop())

    with patch.object(poller, 'fetch_cheese_tracker', AsyncMock(return_value=fetch_result)), \
         patch.object(poller, 'unlink_deleted_tracker', unlink), \
         patch.object(poller, 'process_cheese_update', process):
        asyncio.run(go())
    return unlink, process


class TestPollDecidesWhenATrackerIsGone(unittest.TestCase):
    def test_a_404_from_cheese_unlinks(self):
        unlink, process = _run_poll((None, 404, True))

        unlink.assert_called_once_with(7, 'ct_dead')
        process.assert_not_called()

    def test_nothing_else_unlinks(self):
        """Every one of these is an outage, a throttle or something in front of
        Cheese, not Cheese saying the tracker is gone."""
        for label, result in (
            ("404 from a proxy or wrong base URL", (None, 404, False)),
            ("server error", (None, 500, True)),
            ("rate limited", (None, 429, True)),
            ("no response at all", (None, 0, False)),
            ("gone, but phrased as 410", (None, 410, True)),
        ):
            with self.subTest(label):
                unlink, process = _run_poll(result)
                unlink.assert_not_called()
                process.assert_not_called()

    def test_a_live_tracker_is_processed_as_before(self):
        unlink, process = _run_poll(({'updated_at': '2026-09-14T10:00:00Z'}, 200, True))

        unlink.assert_not_called()
        process.assert_called_once()


class _FakeResponse:
    def __init__(self, status, headers=None, body=None):
        self.status = status
        self.headers = CIMultiDict(headers or {})
        self._body = body

    async def json(self, content_type=None):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _fetch(response=None, raises=None):
    session = MagicMock()
    if raises:
        session.get.side_effect = raises
    else:
        session.get.return_value = response
    with patch.object(poller, 'get_aiohttp_session', return_value=session):
        return asyncio.run(poller.fetch_cheese_tracker("http://cheese/api/tracker/x"))


class TestFetchCheeseTracker(unittest.TestCase):
    CHEESE = {'X-CT-Settings': '{"build_version":"abc"}'}

    def test_cheese_404_is_recognised_whatever_the_header_case(self):
        """aiohttp headers are case-insensitive; production sends it lower-case."""
        self.assertEqual(_fetch(_FakeResponse(404, self.CHEESE)), (None, 404, True))

    def test_a_404_without_the_cheese_header_is_not_cheese(self):
        self.assertEqual(_fetch(_FakeResponse(404, {'Server': 'nginx'})), (None, 404, False))

    def test_a_tracker_comes_back_with_its_payload(self):
        self.assertEqual(_fetch(_FakeResponse(200, self.CHEESE, {'updated_at': 'x'})),
                         ({'updated_at': 'x'}, 200, True))

    def test_a_200_that_is_not_a_tracker_is_no_data(self):
        """A misrouted base URL returns the site's HTML shell with a 200."""
        for body in (['not', 'an', 'object'], ValueError("not json")):
            with self.subTest(body=body):
                self.assertEqual(_fetch(_FakeResponse(200, {}, body)), (None, 200, False))

    def test_a_network_failure_is_status_zero(self):
        self.assertEqual(_fetch(raises=asyncio.TimeoutError()), (None, 0, False))


if __name__ == '__main__':
    unittest.main()
