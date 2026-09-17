"""A claim or release that did not reach Cheese is retried, not lost (#304).

The slot route commits locally and pushes afterwards. When the push failed, the
app said Playing while the slot stayed open on Cheese, and the next poll saw it
unclaimed and demoted it with a "Slot Released" push. Now the failed slot is
remembered, the sync leaves it alone, and the poller pushes it again.
"""
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import requests

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_cheese_pending_push.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

from app import create_app, Session, engine
from app import api_cheese
from app.api_cheese import (
    CHEESE_PENDING_MAX_ATTEMPTS, push_slot_changes_to_cheese, retry_pending_cheese_pushes,
)
from app.encryption import encrypt_api_key
from app.models import (
    Base, CheesePendingPush, TrackedRoom, User, UserRoomSubscription, UserTrackedSlot,
)
from app.services.cheese_service import process_cheese_update
from app.services.retention_service import purge_stale_cheese_pending_pushes
from app.utils import CHEESE_LINK_LINKED, CHEESE_LINK_NONE

MY_CT_ID = 12345
OTHER_CT_ID = 99999
TRACKER = 'ct_room_1'


def game(position, owner=None):
    return {
        'id': 90 + position,
        'position': position,
        'claimed_by_ct_user_id': owner,
        'discord_username': None,
        'effective_discord_username': None,
        'availability_status': 'claimed' if owner else 'open',
    }


def tracker(*games):
    return {'tracker_id': TRACKER, 'updated_at': '2026-09-17T10:00:00Z', 'games': list(games)}


def response(status, body=None):
    resp = MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body if body is not None else {}
    resp.text = ''
    return resp


def _remove_test_db():
    for suffix in ('', '-wal', '-shm'):
        path = f"{TEST_DB_PATH}{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


class PendingPushTestBase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.session = Session()

        self.session.add_all([
            User(id=1, discord_username='player', cheese_api_key=encrypt_api_key('key'),
                 cheese_user_id=MY_CT_ID, is_guest=False),
            TrackedRoom(id=10, room_id='room_uuid', hostname='archipelago.gg',
                        cheese_tracker_id=TRACKER, cached_players_json='[]',
                        cheese_updated_at=datetime(2026, 9, 1)),
        ])
        self.session.flush()
        self.session.add(UserRoomSubscription(user_id=1, room_id=10, alias='Room',
                                              cheese_link=CHEESE_LINK_LINKED))
        self.session.commit()

    def tearDown(self):
        self.session.close()
        Session.remove()
        engine.dispose()
        self.app_context.pop()
        _remove_test_db()

    def slot(self, slot_id, mode='play'):
        self.session.add(UserTrackedSlot(user_id=1, room_id=10, slot_id=slot_id, track_mode=mode))
        self.session.commit()

    def pend(self, slot_id, attempts=1, created_at=None):
        self.session.add(CheesePendingPush(
            user_id=1, cheese_tracker_id=TRACKER, slot_id=slot_id, attempts=attempts,
            created_at=created_at or datetime.utcnow(),
        ))
        self.session.commit()

    def pending(self):
        fresh = Session()
        try:
            return {row.slot_id: row.attempts for row in fresh.query(CheesePendingPush).all()}
        finally:
            fresh.close()

    def mode(self, slot_id):
        fresh = Session()
        try:
            return fresh.query(UserTrackedSlot).filter_by(user_id=1, slot_id=slot_id).one().track_mode
        finally:
            fresh.close()


@patch('app.api_cheese._cheese_session.put')
@patch('app.api_cheese._cheese_session.get')
class TestAFailedPushIsRemembered(PendingPushTestBase):
    def test_a_timeout_reading_the_tracker_leaves_every_slot_pending(self, mock_get, mock_put):
        """The production failure: the read before the write timed out."""
        mock_get.side_effect = requests.exceptions.ReadTimeout("read timed out")

        push_slot_changes_to_cheese(self.app, 1, 10, {1, 2}, {3})

        mock_put.assert_not_called()
        self.assertEqual(self.pending(), {1: 1, 2: 1, 3: 1})

    def test_a_timeout_on_the_write_leaves_that_slot_pending(self, mock_get, mock_put):
        mock_get.return_value = response(200, tracker(game(1), game(2)))
        mock_put.side_effect = [response(200), requests.exceptions.ReadTimeout("read timed out")]

        push_slot_changes_to_cheese(self.app, 1, 10, [1, 2], set())

        self.assertEqual(self.pending(), {2: 1})

    def test_a_server_error_is_retried_but_a_refusal_is_not(self, mock_get, mock_put):
        """A 4xx, the owner precondition included, is Cheese's answer. The sync
        reconciles from it; retrying would only be refused again."""
        mock_get.return_value = response(200, tracker(game(1), game(2)))
        mock_put.side_effect = lambda url, **kw: response(503 if url.endswith('/91') else 412)

        push_slot_changes_to_cheese(self.app, 1, 10, {1, 2}, set())

        self.assertEqual(self.pending(), {1: 1})

    def test_a_slot_someone_else_holds_is_not_retried(self, mock_get, mock_put):
        mock_get.return_value = response(200, tracker(game(1, owner=OTHER_CT_ID)))

        push_slot_changes_to_cheese(self.app, 1, 10, {1}, set())

        mock_put.assert_not_called()
        self.assertEqual(self.pending(), {})

    def test_a_push_that_lands_clears_the_slot(self, mock_get, mock_put):
        self.pend(1, attempts=2)
        mock_get.return_value = response(200, tracker(game(1)))
        mock_put.return_value = response(200)

        push_slot_changes_to_cheese(self.app, 1, 10, {1}, set())

        self.assertEqual(self.pending(), {})

    def test_another_failure_counts_an_attempt(self, mock_get, mock_put):
        self.pend(1, attempts=2)
        mock_get.side_effect = requests.exceptions.ConnectTimeout("connect timed out")

        push_slot_changes_to_cheese(self.app, 1, 10, {1}, set())

        self.assertEqual(self.pending(), {1: 3})

    def test_it_gives_up_after_the_last_attempt(self, mock_get, mock_put):
        self.pend(1, attempts=CHEESE_PENDING_MAX_ATTEMPTS)
        mock_get.side_effect = requests.exceptions.ConnectTimeout("connect timed out")

        push_slot_changes_to_cheese(self.app, 1, 10, {1}, set())

        self.assertEqual(self.pending(), {})

    def test_a_claim_the_link_no_longer_allows_is_not_pending(self, mock_get, mock_put):
        """Unlinked: the release still goes, the claim is dropped, and a dropped
        claim must not wait around to be retried."""
        self.pend(2)
        fresh = Session()
        fresh.get(UserRoomSubscription, (1, 10)).cheese_link = CHEESE_LINK_NONE
        fresh.commit()
        fresh.close()
        mock_get.side_effect = requests.exceptions.ReadTimeout("read timed out")

        push_slot_changes_to_cheese(self.app, 1, 10, {2}, {1})

        self.assertEqual(self.pending(), {1: 1})


class TestTheSyncLeavesAPendingClaimAlone(PendingPushTestBase):
    def test_a_pending_claim_seen_unclaimed_stays_playing(self):
        self.slot(1)
        self.pend(1)

        payload = process_cheese_update(10, tracker(game(1)), '2026-09-17T10:00:00Z')

        self.assertEqual(self.mode(1), 'play')
        self.assertEqual(payload, {}, "no 'Slot Released' push for a slot the user just picked")

    def test_without_a_pending_claim_it_is_still_demoted(self):
        """Auto-release must keep working."""
        self.slot(1)

        process_cheese_update(10, tracker(game(1)), '2026-09-17T10:00:00Z')

        self.assertEqual(self.mode(1), 'watch')

    def test_a_pending_claim_someone_else_took_is_still_demoted(self):
        self.slot(1)
        self.pend(1)

        process_cheese_update(10, tracker(game(1, owner=OTHER_CT_ID)), '2026-09-17T10:00:00Z')

        self.assertEqual(self.mode(1), 'watch')


class TestThePollerRetries(PendingPushTestBase):
    def test_each_slot_is_pushed_as_its_current_mode_asks(self):
        """Playing is claimed; watching or untracked is released. The last thing
        the user did wins, whatever failed before it."""
        self.slot(1, 'play')
        self.slot(2, 'watch')
        for slot_id in (1, 2, 3):
            self.pend(slot_id)
        snapshot = tracker(game(1), game(2, MY_CT_ID), game(3, MY_CT_ID))

        with patch.object(api_cheese, 'push_slot_changes_to_cheese', return_value={}) as push:
            retry_pending_cheese_pushes(self.app, TRACKER, snapshot)

        push.assert_called_once()
        user_id, room_id, claims, releases = push.call_args.args[1:5]
        self.assertEqual((user_id, room_id, claims, releases), (1, 10, {1}, {2, 3}))
        self.assertIs(push.call_args.kwargs['tracker_details'], snapshot)

    @patch('app.api_cheese._cheese_session.put')
    @patch('app.api_cheese._cheese_session.get')
    def test_a_retry_that_lands_clears_it_without_refetching(self, mock_get, mock_put):
        self.slot(1)
        self.pend(1)
        mock_put.return_value = response(200)

        retry_pending_cheese_pushes(self.app, TRACKER, tracker(game(1)))

        mock_get.assert_not_called()
        self.assertEqual(mock_put.call_count, 1)
        self.assertEqual(mock_put.call_args.kwargs['json']['claimed_by_ct_user_id'], MY_CT_ID)
        self.assertEqual(self.pending(), {})

    def test_nothing_pending_pushes_nothing(self):
        with patch.object(api_cheese, 'push_slot_changes_to_cheese') as push:
            retry_pending_cheese_pushes(self.app, TRACKER, tracker(game(1)))
        push.assert_not_called()

    def test_rows_nobody_can_push_are_dropped(self):
        """No key left to push with: retrying would only fail forever."""
        self.slot(1)
        self.pend(1)
        fresh = Session()
        fresh.get(User, 1).cheese_api_key = None
        fresh.commit()
        fresh.close()

        retry_pending_cheese_pushes(self.app, TRACKER, tracker(game(1)))

        self.assertEqual(self.pending(), {})


class TestThePollTriggersTheRetry(unittest.TestCase):
    """The retry runs after the sync, with the poll's own snapshot, and only once
    Cheese has answered."""

    def _poll(self, fetched):
        import asyncio
        from unittest.mock import AsyncMock
        from app import poller

        calls = []
        process = MagicMock(side_effect=lambda *a: calls.append('sync') or {})
        retry = MagicMock(side_effect=lambda *a: calls.append('retry'))
        flask_app = object()
        room_info = {'db_id': 10, 'cheese_tracker_id': TRACKER, 'cheese_updated_at': None,
                     'app': flask_app}

        async def go():
            await poller.run_cheese_poll(room_info, asyncio.get_running_loop())

        with patch.object(poller, 'fetch_cheese_tracker', AsyncMock(return_value=fetched)),              patch.object(poller, 'process_cheese_update', process),              patch.object(api_cheese, 'retry_pending_cheese_pushes', retry):
            asyncio.run(go())
        return calls, retry, flask_app

    def test_after_a_poll_cheese_answered(self):
        snapshot = tracker(game(1))
        calls, retry, flask_app = self._poll((snapshot, 200, True))

        self.assertEqual(calls, ['sync', 'retry'])
        self.assertEqual(retry.call_args.args, (flask_app, TRACKER, snapshot))

    def test_not_when_cheese_did_not_answer(self):
        calls, retry, _ = self._poll((None, 503, False))

        retry.assert_not_called()


class TestStaleRowsArePurged(PendingPushTestBase):
    def test_only_rows_past_the_age_limit_go(self):
        self.pend(1, created_at=datetime.utcnow() - timedelta(days=8))
        self.pend(2, created_at=datetime.utcnow() - timedelta(days=1))

        result = purge_stale_cheese_pending_pushes()

        self.assertEqual(result, {'purged_cheese_pending_pushes': 1})
        self.assertEqual(self.pending(), {2: 1})


if __name__ == '__main__':
    unittest.main()
