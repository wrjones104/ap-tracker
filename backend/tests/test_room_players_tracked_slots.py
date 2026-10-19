"""
Tests for GET /rooms/<id>/players listing every slot the user tracks.

The slot picker (Manage Slots) seeds its ticks from this route and saves by
sending the ticked rows to PUT /rooms/<id>/slots, which replaces the user's
tracked set. The route used to build its rows only from the room's cached
player list, so a tracked slot missing from that cache never reached the app
and any save untracked it; with an empty cache, a save untracked every slot.
See #457.
"""
import json
import os
import sys
import unittest

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_room_players_tracked_slots.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import Base, User, TrackedRoom, UserRoomSubscription, UserTrackedSlot


def _make_token(app, user_id):
    """Generate a JWT for the given user_id matching the token_required format."""
    import jwt as pyjwt
    import uuid
    from datetime import datetime, timezone, timedelta
    payload = {
        'user_id': user_id,
        'jti': str(uuid.uuid4()),
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')


def _remove_test_db():
    for suffix in ('', '-wal', '-shm'):
        path = f"{TEST_DB_PATH}{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def _player(slot_id):
    return {
        'slot_id': slot_id,
        'name': f'Player{slot_id}',
        'alias': None,
        'game': 'A Link to the Past',
        'is_finished': False,
        'total_locations': 216,
    }


class TestRoomPlayersListsTrackedSlots(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.client = self.app.test_client()

        session = Session()
        try:
            user = User(discord_id='user_players', discord_username='PlayersUser')
            other = User(discord_id='other_players', discord_username='OtherUser')
            session.add_all([user, other])
            session.flush()
            self.user_id = user.id
            self.other_id = other.id

            room = TrackedRoom(room_id='room-uuid-players', cached_players_json='[]')
            session.add(room)
            session.flush()
            self.room_id = room.id

            session.add(UserRoomSubscription(user_id=user.id, room_id=room.id, alias='Async'))
            session.add(UserRoomSubscription(user_id=other.id, room_id=room.id, alias='Async'))
            session.commit()
        finally:
            Session.remove()

        self.token = _make_token(self.app, self.user_id)

    def tearDown(self):
        Session.remove()
        # Before unlinking, so the pool cannot go on serving an unlinked inode on Linux.
        engine.dispose()
        _remove_test_db()

    def _set_cache(self, players):
        session = Session()
        try:
            room = session.get(TrackedRoom, self.room_id)
            room.cached_players_json = players if isinstance(players, str) else json.dumps(players)
            session.commit()
        finally:
            Session.remove()

    def _track(self, user_id, slot_id, track_mode='watch'):
        session = Session()
        try:
            session.add(UserTrackedSlot(
                user_id=user_id, room_id=self.room_id, slot_id=slot_id, track_mode=track_mode
            ))
            session.commit()
        finally:
            Session.remove()

    def _tracked_ids(self):
        session = Session()
        try:
            rows = session.query(UserTrackedSlot).filter_by(
                user_id=self.user_id, room_id=self.room_id
            ).all()
            return sorted(r.slot_id for r in rows)
        finally:
            Session.remove()

    def _players(self):
        response = self.client.get(
            f'/rooms/{self.room_id}/players',
            headers={'Authorization': f'Bearer {self.token}'}
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_empty_cache_still_lists_tracked_slots(self):
        self._track(self.user_id, 3)
        self._track(self.user_id, 9, track_mode='play')

        rows = self._players()

        self.assertEqual([r['slot_id'] for r in rows], [3, 9])
        for row in rows:
            self.assertTrue(row['is_tracked'])
            self.assertEqual(row['name'], f"Player {row['slot_id']}")
            self.assertIsNone(row['game'])
        self.assertEqual(rows[0]['track_mode'], 'watch')
        self.assertEqual(rows[1]['track_mode'], 'play')

    def test_partial_cache_appends_the_missing_tracked_slot(self):
        self._set_cache([_player(1), _player(2)])
        self._track(self.user_id, 2)
        self._track(self.user_id, 5)

        rows = self._players()

        self.assertEqual([r['slot_id'] for r in rows], [1, 2, 5])
        by_id = {r['slot_id']: r for r in rows}
        self.assertFalse(by_id[1]['is_tracked'])
        self.assertTrue(by_id[2]['is_tracked'])
        self.assertEqual(by_id[2]['name'], 'Player2')
        self.assertTrue(by_id[5]['is_tracked'])
        self.assertEqual(by_id[5]['name'], 'Player 5')

    def test_full_cache_adds_no_rows(self):
        self._set_cache([_player(1), _player(2), _player(3)])
        self._track(self.user_id, 2)

        rows = self._players()

        self.assertEqual([r['slot_id'] for r in rows], [1, 2, 3])
        self.assertEqual([r['slot_id'] for r in rows if r['is_tracked']], [2])

    def test_string_slot_ids_in_the_cache_are_not_duplicated(self):
        # Cached slot ids are normally ints, but the route has always accepted
        # numeric strings. A tracked slot listed that way must not appear twice.
        self._set_cache([{**_player(4), 'slot_id': '4'}])
        self._track(self.user_id, 4)

        rows = self._players()

        self.assertEqual([r['slot_id'] for r in rows], [4])
        self.assertTrue(rows[0]['is_tracked'])

    def test_another_users_tracked_slot_is_not_listed(self):
        self._set_cache([_player(1)])
        self._track(self.other_id, 6)

        rows = self._players()

        self.assertEqual([r['slot_id'] for r in rows], [1])

    def test_saving_the_ticked_rows_keeps_a_slot_missing_from_the_cache(self):
        # What the picker does: tick what the route reports as tracked, then save.
        self._track(self.user_id, 5)

        ticked = [r['slot_id'] for r in self._players() if r['is_tracked']]
        response = self.client.put(
            f'/rooms/{self.room_id}/slots',
            headers={'Authorization': f'Bearer {self.token}'},
            json={'tracked_slot_ids': ticked},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._tracked_ids(), [5])


if __name__ == '__main__':
    unittest.main()
