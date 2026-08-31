"""
Tests for the play/watch split on tracked slots.

The invariant these lock down: tracking a slot ("alert me") and claiming it on
Cheese Tracker ("this is mine") are separate. Losing a claim demotes a slot to
watch; it never deletes it. Watch slots are never written to Cheese and are
never touched by the sync.
"""
import os
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

# Set up test DB and config before importing the app
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_track_mode.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='  # Valid Fernet key

from backend.app import create_app, Session, engine
from backend.app.models import Base, User, TrackedRoom, UserRoomSubscription, UserTrackedSlot
from backend.app.services.cheese_service import process_cheese_update
from backend.app.api_cheese import setup_cheese_user_task
from backend.app.encryption import encrypt_api_key
from backend.app.utils import TRACK_MODE_PLAY, TRACK_MODE_WATCH, normalize_track_mode

MY_CT_ID = 12345
OTHER_CT_ID = 99999

# Any non-null cheese_updated_at means "this room has synced before", which is
# what takes process_cheese_update out of its first-sync grace period.
NOT_FIRST_SYNC = datetime(2026, 1, 1)


class TrackModeTestBase(unittest.TestCase):
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
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

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

    def make_room_with_slot(self, user, slot_id=1, track_mode=TRACK_MODE_PLAY, cheese_updated_at=None):
        room = TrackedRoom(
            room_id="room_uuid",
            cheese_tracker_id="ct_room_1",
            cheese_updated_at=cheese_updated_at,
        )
        self.session.add(room)
        self.session.flush()

        self.session.add(UserRoomSubscription(
            user_id=user.id, room_id=room.id, alias="Test Room"
        ))
        self.session.flush()

        self.session.add(UserTrackedSlot(
            user_id=user.id, room_id=room.id, slot_id=slot_id, track_mode=track_mode
        ))
        self.session.commit()
        return room

    def get_slot(self, user_id, room_id, slot_id):
        fresh = Session()
        try:
            return fresh.query(UserTrackedSlot).filter_by(
                user_id=user_id, room_id=room_id, slot_id=slot_id
            ).first()
        finally:
            fresh.close()


class TestNormalizeTrackMode(unittest.TestCase):
    def test_valid_modes_pass_through(self):
        self.assertEqual(normalize_track_mode('play'), TRACK_MODE_PLAY)
        self.assertEqual(normalize_track_mode('watch'), TRACK_MODE_WATCH)

    def test_garbage_falls_back_to_play(self):
        for value in (None, '', 'spectator', 'PLAY', 7, object()):
            self.assertEqual(normalize_track_mode(value), TRACK_MODE_PLAY)


class TestSingleCheeseSyncImplementation(unittest.TestCase):
    """
    poller.py used to carry its own copy of process_cheese_update. The copy went
    stale and was what actually ran for the background Cheese poll and for
    api_cheese.refresh_tracker_cache, so a fix applied to cheese_service alone
    silently did nothing. Pin the identity so a duplicate cannot come back.
    """

    def test_poller_reexports_the_service_implementation(self):
        import app.poller as live_poller
        from app.services.cheese_service import process_cheese_update as service_impl

        self.assertIs(
            live_poller.process_cheese_update,
            service_impl,
            "app.poller must re-export cheese_service.process_cheese_update, not redefine it",
        )

    def test_cheese_service_source_is_the_only_definition(self):
        import ast
        import pathlib

        backend = pathlib.Path(__file__).resolve().parents[1]
        definitions = []
        for path in (backend / 'app').rglob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == 'process_cheese_update':
                        definitions.append(path.name)

        self.assertEqual(
            definitions,
            ['cheese_service.py'],
            f"process_cheese_update must be defined once, in cheese_service.py. Found: {definitions}",
        )


class TestPollerSyncDemotes(TrackModeTestBase):
    """process_cheese_update must demote, not delete, on claim changes."""

    def _tracker_payload(self, games):
        return {'games': games, 'room_link': None}

    def test_other_user_claim_demotes_play_slot(self):
        user = self.make_user()
        # Not a first sync: cheese_updated_at is already set.
        room = self.make_room_with_slot(user, cheese_updated_at=NOT_FIRST_SYNC)
        room_id = room.id

        process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': OTHER_CT_ID}
        ]), '2026-06-23T10:00:00Z')

        slot = self.get_slot(user.id, room_id, 1)
        self.assertIsNotNone(slot, "slot must survive a lost claim")
        self.assertEqual(slot.track_mode, TRACK_MODE_WATCH)

    def test_remote_unclaimed_demotes_play_slot(self):
        """Auto-release: the host's tracker released the slot out from under us."""
        user = self.make_user()
        room = self.make_room_with_slot(user, cheese_updated_at=NOT_FIRST_SYNC)
        room_id = room.id

        process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': None}
        ]), '2026-06-23T10:00:00Z')

        slot = self.get_slot(user.id, room_id, 1)
        self.assertIsNotNone(slot, "auto-released slot must remain trackable")
        self.assertEqual(slot.track_mode, TRACK_MODE_WATCH)

    def test_watch_slot_is_untouched_by_other_user_claim(self):
        user = self.make_user()
        room = self.make_room_with_slot(user, track_mode=TRACK_MODE_WATCH,
                                        cheese_updated_at=NOT_FIRST_SYNC)
        room_id = room.id

        process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': OTHER_CT_ID,
             'effective_discord_username': 'someone_else'}
        ]), '2026-06-23T10:00:00Z')

        slot = self.get_slot(user.id, room_id, 1)
        self.assertIsNotNone(slot)
        self.assertEqual(slot.track_mode, TRACK_MODE_WATCH)

    def test_own_claim_keeps_play_mode(self):
        user = self.make_user()
        room = self.make_room_with_slot(user, cheese_updated_at=NOT_FIRST_SYNC)
        room_id = room.id

        process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': MY_CT_ID}
        ]), '2026-06-23T10:00:00Z')

        slot = self.get_slot(user.id, room_id, 1)
        self.assertIsNotNone(slot)
        self.assertEqual(slot.track_mode, TRACK_MODE_PLAY)

    def test_vanished_slot_is_still_deleted(self):
        """A slot that no longer exists on the tracker has nothing left to watch."""
        user = self.make_user()
        room = self.make_room_with_slot(user, cheese_updated_at=NOT_FIRST_SYNC)
        room_id = room.id

        process_cheese_update(room_id, self._tracker_payload([]), '2026-06-23T10:00:00Z')

        self.assertIsNone(self.get_slot(user.id, room_id, 1))

    def test_first_sync_grace_period_still_applies(self):
        user = self.make_user()
        room = self.make_room_with_slot(user, cheese_updated_at=None)
        room_id = room.id

        process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': None}
        ]), '2026-06-23T10:00:00Z')

        slot = self.get_slot(user.id, room_id, 1)
        self.assertIsNotNone(slot)
        self.assertEqual(slot.track_mode, TRACK_MODE_PLAY)


class TestUpdateTrackedSlotsRouting(TrackModeTestBase):
    """
    The PUT route must derive Cheese claims/releases from track_mode
    transitions rather than from tracking alone.
    """

    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.room = TrackedRoom(room_id="room_uuid", cheese_tracker_id="ct_room_1")
        self.session.add(self.room)
        self.session.flush()
        self.session.add(UserRoomSubscription(
            user_id=self.user.id, room_id=self.room.id, alias="Test Room"
        ))
        self.session.commit()
        self.room_id = self.room.id

        self.client = self.app.test_client()

    def _put(self, payload):
        """
        Calls the route body directly, capturing what it would have pushed to
        Cheese.

        The Flask app under test resolves its own `app.*` package while these
        tests import `backend.app.*`, so those are distinct module objects and
        patching the push function by name is unreliable. Intercepting
        threading.Thread is not: it is the same module either way, and the args
        the route hands it are exactly the claim/release sets under test.
        """
        from backend.app.routes import slots_routes
        import app.poller as live_poller

        pushes = []

        def fake_thread(target=None, args=(), **kwargs):
            # args == (app_context, user_id, room_db_id, claims, releases)
            if len(args) == 5:
                pushes.append({'claims': set(args[3]), 'releases': set(args[4])})
            return MagicMock()

        with patch('threading.Thread', side_effect=fake_thread), \
             patch.object(live_poller, 'trigger_immediate_room_poll', lambda *a, **k: None):
            with self.app.test_request_context(json=payload):
                resp = slots_routes.update_tracked_slots.__wrapped__.__wrapped__.__wrapped__(
                    self.user, self.room_id
                )
        return resp, pushes

    def _add_slot(self, slot_id, mode):
        self.session.add(UserTrackedSlot(
            user_id=self.user.id, room_id=self.room_id, slot_id=slot_id, track_mode=mode
        ))
        self.session.commit()

    def test_tracking_as_watch_never_pushes_to_cheese(self):
        _, pushes = self._put({
            'tracked_slot_ids': [1],
            'slot_modes': {'1': 'watch'},
        })
        self.assertEqual(pushes, [], "watch-only changes must not reach Cheese")

        slot = self.get_slot(self.user.id, self.room_id, 1)
        self.assertIsNotNone(slot)
        self.assertEqual(slot.track_mode, TRACK_MODE_WATCH)

    def test_tracking_as_play_claims(self):
        _, pushes = self._put({
            'tracked_slot_ids': [1],
            'slot_modes': {'1': 'play'},
        })
        self.assertEqual(len(pushes), 1)
        self.assertEqual(pushes[0]['claims'], {1})
        self.assertEqual(pushes[0]['releases'], set())

    def test_play_to_watch_releases_but_keeps_the_slot(self):
        self._add_slot(1, TRACK_MODE_PLAY)
        _, pushes = self._put({
            'tracked_slot_ids': [1],
            'slot_modes': {'1': 'watch'},
        })
        self.assertEqual(len(pushes), 1)
        self.assertEqual(pushes[0]['releases'], {1})
        self.assertEqual(pushes[0]['claims'], set())

        slot = self.get_slot(self.user.id, self.room_id, 1)
        self.assertIsNotNone(slot, "switching to watch must not untrack the slot")
        self.assertEqual(slot.track_mode, TRACK_MODE_WATCH)

    def test_watch_to_play_claims(self):
        self._add_slot(1, TRACK_MODE_WATCH)
        _, pushes = self._put({
            'tracked_slot_ids': [1],
            'slot_modes': {'1': 'play'},
        })
        self.assertEqual(len(pushes), 1)
        self.assertEqual(pushes[0]['claims'], {1})

    def test_untracking_a_watch_slot_does_not_release_on_cheese(self):
        self._add_slot(1, TRACK_MODE_WATCH)
        _, pushes = self._put({'tracked_slot_ids': []})
        self.assertEqual(pushes, [], "we never claimed it, so we must not unclaim it")
        self.assertIsNone(self.get_slot(self.user.id, self.room_id, 1))

    def test_untracking_a_play_slot_releases(self):
        self._add_slot(1, TRACK_MODE_PLAY)
        _, pushes = self._put({'tracked_slot_ids': []})
        self.assertEqual(len(pushes), 1)
        self.assertEqual(pushes[0]['releases'], {1})

    def test_legacy_client_without_slot_modes_preserves_existing_mode(self):
        """An older app build re-saving the picker must not re-claim watched slots."""
        self._add_slot(1, TRACK_MODE_WATCH)
        self._add_slot(2, TRACK_MODE_PLAY)

        _, pushes = self._put({'tracked_slot_ids': [1, 2]})

        self.assertEqual(pushes, [], "a no-op save must not touch Cheese")
        self.assertEqual(self.get_slot(self.user.id, self.room_id, 1).track_mode, TRACK_MODE_WATCH)
        self.assertEqual(self.get_slot(self.user.id, self.room_id, 2).track_mode, TRACK_MODE_PLAY)

    def test_legacy_client_new_slots_default_to_play(self):
        _, pushes = self._put({'tracked_slot_ids': [3]})
        self.assertEqual(len(pushes), 1)
        self.assertEqual(pushes[0]['claims'], {3})
        self.assertEqual(self.get_slot(self.user.id, self.room_id, 3).track_mode, TRACK_MODE_PLAY)

    def test_invalid_mode_is_rejected(self):
        resp = self._put({
            'tracked_slot_ids': [1],
            'slot_modes': {'1': 'spectator'},
        })[0]
        self.assertEqual(resp[1], 400)


class TestSetupDemotesOnMidAsyncConnect(TrackModeTestBase):
    """Connecting to Cheese mid-async must not cost the user their slots."""

    @patch('backend.app.api_cheese.requests.Session')
    def test_unconfirmed_slots_demote_instead_of_being_pruned(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session

        me_resp = MagicMock(ok=True)
        me_resp.json.return_value = {'id': MY_CT_ID, 'discord_username': 'me'}

        dash_resp = MagicMock(ok=True)
        dash_resp.json.return_value = [{
            'tracker_id': 'ct_room_1',
            'room_link': 'https://archipelago.gg/room/room_uuid',
            'title': 'Test Room',
            'dashboard_override_visibility': True,
        }]

        detail_resp = MagicMock(ok=True)
        detail_resp.json.return_value = {
            'updated_at': '2026-06-23T10:00:00Z',
            'games': [
                # Slot 1 really is theirs.
                {'id': 901, 'position': 1, 'claimed_by_ct_user_id': MY_CT_ID},
                # Slot 2 belongs to someone else.
                {'id': 902, 'position': 2, 'claimed_by_ct_user_id': OTHER_CT_ID},
                # Slot 3 is unclaimed.
                {'id': 903, 'position': 3, 'claimed_by_ct_user_id': None},
            ],
        }

        def mock_get(url, *args, **kwargs):
            if '/user/self' in url:
                return me_resp
            if '/dashboard/tracker' in url:
                return dash_resp
            if '/tracker/ct_room_1' in url:
                return detail_resp
            return MagicMock()

        mock_session.get.side_effect = mock_get

        user = self.make_user(is_syncing_cheese=True)

        # The user was already tracking all three slots before connecting.
        room = TrackedRoom(room_id="room_uuid")
        self.session.add(room)
        self.session.flush()
        self.session.add(UserRoomSubscription(
            user_id=user.id, room_id=room.id, alias="Test Room"
        ))
        self.session.flush()
        for slot_id in (1, 2, 3):
            self.session.add(UserTrackedSlot(
                user_id=user.id, room_id=room.id, slot_id=slot_id, track_mode=TRACK_MODE_PLAY
            ))
        self.session.commit()
        room_id = room.id
        user_id = user.id

        setup_cheese_user_task(self.app, user_id)

        fresh = Session()
        try:
            slots = {
                s.slot_id: s for s in
                fresh.query(UserTrackedSlot).filter_by(user_id=user_id, room_id=room_id).all()
            }
            self.assertEqual(set(slots), {1, 2, 3}, "no slot may be lost on connect")
            self.assertEqual(slots[1].track_mode, TRACK_MODE_PLAY)
            self.assertEqual(slots[2].track_mode, TRACK_MODE_WATCH)
            self.assertEqual(slots[3].track_mode, TRACK_MODE_WATCH)

            updated_user = fresh.query(User).get(user_id)
            self.assertFalse(updated_user.is_syncing_cheese)
            self.assertEqual(updated_user.cheese_last_sync_demoted, 2)
        finally:
            fresh.close()


if __name__ == '__main__':
    unittest.main()
