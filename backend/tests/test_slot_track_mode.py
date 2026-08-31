"""
Tests for the play/watch split on tracked slots.

The invariant these lock down: tracking a slot ("alert me") and claiming it on
Cheese Tracker ("this is mine") are separate. Losing a claim demotes a slot to
watch; it never deletes it. Watch slots are never written to Cheese and are
never touched by the sync.
"""
import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

# Set up test DB and config before importing the app
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_track_mode.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='  # Valid Fernet key

# Import through `app.*` only, never `backend.app.*`. The two resolve to
# separate module objects with separate engines over the same SQLite file, and
# the app itself mixes styles: cheese_service.py uses an absolute `from app
# import Session` while api_cheese.py uses a relative one. Mixing here put the
# fixture on one engine and process_cheese_update on the other, so writes were
# invisible to the code under test -- which surfaced on Linux CI as spurious
# "first sync" reads and disk I/O errors, while passing on Windows.
from app import create_app, Session, engine
from app.models import Base, Device, User, TrackedRoom, UserRoomSubscription, UserTrackedSlot
from app.services.cheese_service import process_cheese_update
from app.api_cheese import setup_cheese_user_task
from app.encryption import encrypt_api_key
from app.utils import TRACK_MODE_PLAY, TRACK_MODE_WATCH, normalize_track_mode

MY_CT_ID = 12345
OTHER_CT_ID = 99999

# Any non-null cheese_updated_at means "this room has synced before", which is
# what takes process_cheese_update out of its first-sync grace period.
NOT_FIRST_SYNC = datetime(2026, 1, 1)


def _remove_test_db():
    """
    Removes the SQLite file and its WAL sidecars. The app enables WAL mode, so
    dropping only the .db leaves -wal and -shm behind for the next test to trip
    over; on Linux that surfaced as "disk I/O error" and "no such table".
    """
    for suffix in ('', '-wal', '-shm'):
        path = f"{TEST_DB_PATH}{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def _run_inline(target=None, args=(), **kwargs):
    """
    Stands in for threading.Thread so the route's background Cheese push runs
    inline, keeping assertions deterministic instead of racing a real thread.
    """
    thread = MagicMock()
    thread.start.side_effect = lambda: target(*args)
    return thread


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

    def make_room_with_slot_for(self, user_id, slot_id=1, track_mode=TRACK_MODE_PLAY,
                                cheese_updated_at=None):
        """
        Builds a room + subscription + tracked slot and returns the room id as a
        plain int.

        Deliberately returns an id rather than the ORM object: the code under
        test calls Session.remove() in its finally block, which detaches any
        instance the test is still holding and turns a later attribute read into
        a DetachedInstanceError.
        """
        room = TrackedRoom(
            room_id="room_uuid",
            cheese_tracker_id="ct_room_1",
            cheese_updated_at=cheese_updated_at,
        )
        self.session.add(room)
        self.session.flush()

        self.session.add(UserRoomSubscription(
            user_id=user_id, room_id=room.id, alias="Test Room"
        ))
        self.session.flush()

        self.session.add(UserTrackedSlot(
            user_id=user_id, room_id=room.id, slot_id=slot_id, track_mode=track_mode
        ))
        self.session.commit()
        return room.id

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


class TestSingleEngine(unittest.TestCase):
    """
    `app` and `backend.app` are separate module objects with separate engines
    over the same SQLite file. A test module that mixes them puts its fixture on
    one engine and the code under test on the other, so writes are invisible
    across the boundary. That passes on Windows and fails on Linux CI, which is
    a miserable thing to debug -- pin it instead.
    """

    def test_code_under_test_shares_the_fixture_engine(self):
        import app.api_cheese as live_cheese
        import app.routes.slots_routes as live_slots
        import app.services.cheese_service as live_service

        for name, module in (
            ('cheese_service', live_service),
            ('api_cheese', live_cheese),
            ('slots_routes', live_slots),
        ):
            self.assertIs(
                module.Session, Session,
                f"{name} must share the fixture's scoped session, or its writes "
                f"land in a different engine than the test reads from",
            )


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
        user_id = self.make_user().id
        # Not a first sync: cheese_updated_at is already set.
        room_id = self.make_room_with_slot_for(user_id, cheese_updated_at=NOT_FIRST_SYNC)

        process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': OTHER_CT_ID}
        ]), '2026-06-23T10:00:00Z')

        slot = self.get_slot(user_id, room_id, 1)
        self.assertIsNotNone(slot, "slot must survive a lost claim")
        self.assertEqual(slot.track_mode, TRACK_MODE_WATCH)

    def test_remote_unclaimed_demotes_play_slot(self):
        """Auto-release: the host's tracker released the slot out from under us."""
        user_id = self.make_user().id
        room_id = self.make_room_with_slot_for(user_id, cheese_updated_at=NOT_FIRST_SYNC)

        process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': None}
        ]), '2026-06-23T10:00:00Z')

        slot = self.get_slot(user_id, room_id, 1)
        self.assertIsNotNone(slot, "auto-released slot must remain trackable")
        self.assertEqual(slot.track_mode, TRACK_MODE_WATCH)

    def test_watch_slot_is_untouched_by_other_user_claim(self):
        user_id = self.make_user().id
        room_id = self.make_room_with_slot_for(
            user_id, track_mode=TRACK_MODE_WATCH, cheese_updated_at=NOT_FIRST_SYNC
        )

        process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': OTHER_CT_ID,
             'effective_discord_username': 'someone_else'}
        ]), '2026-06-23T10:00:00Z')

        slot = self.get_slot(user_id, room_id, 1)
        self.assertIsNotNone(slot)
        self.assertEqual(slot.track_mode, TRACK_MODE_WATCH)

    def test_own_claim_keeps_play_mode(self):
        user_id = self.make_user().id
        room_id = self.make_room_with_slot_for(user_id, cheese_updated_at=NOT_FIRST_SYNC)

        process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': MY_CT_ID}
        ]), '2026-06-23T10:00:00Z')

        slot = self.get_slot(user_id, room_id, 1)
        self.assertIsNotNone(slot)
        self.assertEqual(slot.track_mode, TRACK_MODE_PLAY)

    def test_vanished_slot_is_still_deleted(self):
        """A slot that no longer exists on the tracker has nothing left to watch."""
        user_id = self.make_user().id
        room_id = self.make_room_with_slot_for(user_id, cheese_updated_at=NOT_FIRST_SYNC)

        process_cheese_update(room_id, self._tracker_payload([]), '2026-06-23T10:00:00Z')

        self.assertIsNone(self.get_slot(user_id, room_id, 1))

    def test_first_sync_grace_period_still_applies(self):
        user_id = self.make_user().id
        room_id = self.make_room_with_slot_for(user_id, cheese_updated_at=None)

        process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': None}
        ]), '2026-06-23T10:00:00Z')

        slot = self.get_slot(user_id, room_id, 1)
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
        Cheese. The route imports both of these lazily at call time, so patching
        them at their definition sites is enough.
        """
        from app.routes import slots_routes
        import app.api_cheese as live_cheese
        import app.poller as live_poller

        pushes = []

        def fake_push(app_ctx, user_id, room_db_id, claims, releases):
            pushes.append({'claims': set(claims), 'releases': set(releases)})

        with patch.object(live_cheese, 'push_slot_changes_to_cheese', fake_push), \
             patch.object(live_poller, 'trigger_immediate_room_poll', lambda *a, **k: None), \
             patch('threading.Thread', side_effect=_run_inline):
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

    @patch('app.api_cheese.requests.Session')
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

            updated_user = fresh.get(User, user_id)
            self.assertFalse(updated_user.is_syncing_cheese)
            self.assertEqual(updated_user.cheese_last_sync_demoted, 2)
        finally:
            fresh.close()

    def _run_sync_with_games(self, games, mock_session_cls, existing_modes):
        """
        Runs setup_cheese_user_task against a tracker returning `games`, with the
        user already tracking `existing_modes` ({slot_id: mode}) in the room.
        Returns {slot_id: track_mode} afterwards, plus the demoted count.
        """
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
        detail_resp.json.return_value = {'updated_at': '2026-06-23T10:00:00Z', 'games': games}

        def mock_get(url, *args, **kwargs):
            if '/user/self' in url:
                return me_resp
            if '/dashboard/tracker' in url:
                return dash_resp
            if '/tracker/ct_room_1' in url:
                return detail_resp
            return MagicMock()

        mock_session.get.side_effect = mock_get

        user_id = self.make_user(is_syncing_cheese=True).id

        room = TrackedRoom(room_id="room_uuid")
        self.session.add(room)
        self.session.flush()
        self.session.add(UserRoomSubscription(
            user_id=user_id, room_id=room.id, alias="Test Room"
        ))
        self.session.flush()
        for slot_id, mode in existing_modes.items():
            self.session.add(UserTrackedSlot(
                user_id=user_id, room_id=room.id, slot_id=slot_id, track_mode=mode
            ))
        self.session.commit()
        room_id = room.id

        setup_cheese_user_task(self.app, user_id)

        fresh = Session()
        try:
            modes = {
                s.slot_id: s.track_mode for s in
                fresh.query(UserTrackedSlot).filter_by(user_id=user_id, room_id=room_id).all()
            }
            demoted = fresh.get(User, user_id).cheese_last_sync_demoted
        finally:
            fresh.close()
        return modes, demoted

    @patch('app.api_cheese.requests.Session')
    def test_empty_games_does_not_demote_anything(self, mock_session_cls):
        """
        A tracker with no games carries no ownership information. Treating it as
        evidence would demote every claim in the room in one pass.
        """
        modes, demoted = self._run_sync_with_games(
            [], mock_session_cls, {1: TRACK_MODE_PLAY, 2: TRACK_MODE_PLAY}
        )
        self.assertEqual(modes, {1: TRACK_MODE_PLAY, 2: TRACK_MODE_PLAY})
        self.assertEqual(demoted, 0)

    @patch('app.api_cheese.requests.Session')
    def test_missing_games_key_does_not_demote_anything(self, mock_session_cls):
        modes, demoted = self._run_sync_with_games(
            None, mock_session_cls, {1: TRACK_MODE_PLAY}
        )
        self.assertEqual(modes, {1: TRACK_MODE_PLAY})
        self.assertEqual(demoted, 0)

    @patch('app.api_cheese.requests.Session')
    def test_watch_is_sticky_even_when_cheese_says_the_slot_is_ours(self, mock_session_cls):
        """
        A play -> watch release that never landed leaves Cheese still showing us
        as owner. Re-promoting would silently revert the user's explicit choice.
        """
        modes, _ = self._run_sync_with_games(
            [{'id': 901, 'position': 1, 'claimed_by_ct_user_id': MY_CT_ID}],
            mock_session_cls,
            {1: TRACK_MODE_WATCH},
        )
        self.assertEqual(modes, {1: TRACK_MODE_WATCH})


class TestCheeseSyncLeavesNotifyFinishedInherited(TrackModeTestBase):
    """
    Slots the CT sync creates must inherit User.notify_finished_default, exactly
    as picker-created slots do. Stamping the default in as a concrete value
    writes a permanent per-slot override, so the slot silently stops following
    the global setting the user later changes.
    """

    @patch('app.api_cheese.requests.Session')
    def test_synced_slot_leaves_notify_finished_null(self, mock_session_cls):
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
            'games': [{'id': 901, 'position': 1, 'claimed_by_ct_user_id': MY_CT_ID}],
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

        # Default ON, so a stamped override would be indistinguishable from
        # inheritance until the user flips the global setting off.
        user = self.make_user(is_syncing_cheese=True, notify_finished_default=True)
        user_id = user.id

        room = TrackedRoom(room_id="room_uuid")
        self.session.add(room)
        self.session.flush()
        self.session.add(UserRoomSubscription(
            user_id=user_id, room_id=room.id, alias="Test Room"
        ))
        self.session.commit()
        room_id = room.id

        setup_cheese_user_task(self.app, user_id)

        slot = self.get_slot(user_id, room_id, 1)
        self.assertIsNotNone(slot, "the sync must create the claimed slot")
        self.assertIsNone(
            slot.notify_finished,
            "CT-synced slots must inherit notify_finished_default, not pin it",
        )


class TestPollerSyncNotifiesOnDemotion(TrackModeTestBase):
    """
    run_cheese_poll's push loop is fed by process_cheese_update's return value.
    It returned {} on every path for as long as it existed, so the poller could
    never tell a user their slot had been demoted -- they found out by noticing
    the badge change.
    """

    def _tracker_payload(self, games):
        return {'games': games, 'room_link': None}

    def add_device(self, user_id, token='tok_a', platform='android'):
        self.session.add(Device(
            user_id=user_id, fcm_token=token, android_id=token, platform=platform
        ))
        self.session.commit()

    def set_players(self, room_id, players):
        fresh = Session()
        try:
            room = fresh.get(TrackedRoom, room_id)
            room.cached_players_json = json.dumps(players)
            fresh.commit()
        finally:
            fresh.close()

    def test_other_user_claim_returns_a_conflict_push(self):
        user_id = self.make_user().id
        room_id = self.make_room_with_slot_for(user_id, cheese_updated_at=NOT_FIRST_SYNC)
        self.add_device(user_id)
        self.set_players(room_id, [{'slot_id': 1, 'name': 'Rando', 'alias': 'Zelda'}])

        payload = process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': OTHER_CT_ID}
        ]), '2026-06-23T10:00:00Z')

        self.assertIn(user_id, payload, "a demoted user must get a push payload")
        notifications = payload[user_id]['notifications']
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]['title'], "Slot Already Claimed")
        self.assertIn('Zelda', notifications[0]['body'], "alias beats raw slot number")
        self.assertIn('Test Room', notifications[0]['body'])
        self.assertEqual(payload[user_id]['tokens'], {'android': ['tok_a']})

    def test_auto_release_is_not_reported_as_a_conflict(self):
        """
        The host's tracker releasing a slot is not someone taking it. Telling the
        user it was 'claimed by someone else' would be plainly wrong.
        """
        user_id = self.make_user().id
        room_id = self.make_room_with_slot_for(user_id, cheese_updated_at=NOT_FIRST_SYNC)
        self.add_device(user_id)

        payload = process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': None}
        ]), '2026-06-23T10:00:00Z')

        notifications = payload[user_id]['notifications']
        self.assertEqual(notifications[0]['title'], "Slot Released")
        self.assertNotIn('someone else', notifications[0]['body'])

    def test_no_demotion_returns_nothing_to_send(self):
        user_id = self.make_user().id
        room_id = self.make_room_with_slot_for(user_id, cheese_updated_at=NOT_FIRST_SYNC)
        self.add_device(user_id)

        payload = process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': MY_CT_ID}
        ]), '2026-06-23T10:00:00Z')

        self.assertEqual(payload, {})

    def test_user_without_devices_is_skipped(self):
        user_id = self.make_user().id
        room_id = self.make_room_with_slot_for(user_id, cheese_updated_at=NOT_FIRST_SYNC)

        payload = process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': OTHER_CT_ID}
        ]), '2026-06-23T10:00:00Z')

        self.assertEqual(payload, {}, "no devices means nothing to send")
        self.assertEqual(
            self.get_slot(user_id, room_id, 1).track_mode, TRACK_MODE_WATCH,
            "the demotion itself must still happen",
        )

    def test_first_sync_grace_period_sends_nothing(self):
        user_id = self.make_user().id
        room_id = self.make_room_with_slot_for(user_id, cheese_updated_at=None)
        self.add_device(user_id)

        payload = process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': None}
        ]), '2026-06-23T10:00:00Z')

        self.assertEqual(payload, {})

    def test_tokens_are_grouped_by_platform(self):
        """
        send_push_notifications is called once per platform with that platform's
        Firebase app, so the payload must keep them apart.
        """
        user_id = self.make_user().id
        room_id = self.make_room_with_slot_for(user_id, cheese_updated_at=NOT_FIRST_SYNC)
        self.add_device(user_id, token='tok_android', platform='android')
        self.add_device(user_id, token='tok_ios', platform='ios')

        payload = process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': OTHER_CT_ID}
        ]), '2026-06-23T10:00:00Z')

        self.assertEqual(
            payload[user_id]['tokens'],
            {'android': ['tok_android'], 'ios': ['tok_ios']},
        )

    def test_watch_slot_never_produces_a_push(self):
        user_id = self.make_user().id
        room_id = self.make_room_with_slot_for(
            user_id, track_mode=TRACK_MODE_WATCH, cheese_updated_at=NOT_FIRST_SYNC
        )
        self.add_device(user_id)

        payload = process_cheese_update(room_id, self._tracker_payload([
            {'position': 1, 'claimed_by_ct_user_id': OTHER_CT_ID}
        ]), '2026-06-23T10:00:00Z')

        self.assertEqual(payload, {})


class TestManualRefreshSendsDemotionPushes(unittest.TestCase):
    """
    refresh_tracker_cache reconciles claims for the whole room, not just the
    caller's slots, so a manual refresh can demote someone else's slot. It threw
    process_cheese_update's payload away, which left that path exactly as silent
    as the poller's unreachable loop was before the fix on the other caller.
    """

    def _payload(self, tokens):
        return {7: {'notifications': [{'title': 'Slot Released', 'body': 'b', 'type': 'conflict'}],
                    'tokens': tokens}}

    @patch('app.services.notification_service.send_fcm_notifications')
    def test_each_platform_is_sent_through_its_own_app(self, mock_send):
        from app.api_cheese import _send_demotion_pushes

        _send_demotion_pushes(self._payload({'android': ['tok_a'], 'ios': ['tok_i']}))

        self.assertEqual(mock_send.call_count, 2)
        by_platform = {c.kwargs['platform']: c.args[0] for c in mock_send.call_args_list}
        self.assertEqual(by_platform, {'android': ['tok_a'], 'ios': ['tok_i']})

    @patch('app.services.notification_service.send_fcm_notifications')
    def test_nothing_to_send_makes_no_calls(self, mock_send):
        from app.api_cheese import _send_demotion_pushes

        _send_demotion_pushes({})
        _send_demotion_pushes(None)
        _send_demotion_pushes({7: {'notifications': [], 'tokens': {'android': ['t']}}})
        _send_demotion_pushes({7: {'notifications': [{'title': 't', 'body': 'b'}], 'tokens': {'android': []}}})

        mock_send.assert_not_called()

    @patch('app.services.notification_service.send_fcm_notifications')
    def test_a_failed_push_does_not_abort_the_refresh(self, mock_send):
        """
        The refresh itself succeeded. A push that could not go out must not turn
        that into an error for the caller.
        """
        from app.api_cheese import _send_demotion_pushes
        mock_send.side_effect = RuntimeError("FCM down")

        _send_demotion_pushes(self._payload({'android': ['tok_a']}))

        mock_send.assert_called_once()


if __name__ == '__main__':
    unittest.main()
