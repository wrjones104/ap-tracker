"""
Tests for conditional GET /users/me/tracked-slots (#417).

The app calls this endpoint on every push, periodic sync and resume, and most calls return
what the phone already has. The server tags each body with an ETag and answers 304 Not Modified,
with no body, when the app sends that tag back in If-None-Match.
"""
import json
import os
import sys
import unittest

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_tracked_slots_conditional.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import Base, User, TrackedRoom, UserRoomSubscription, UserTrackedSlot

ROOM_UUID = 'room-uuid-conditional'
SLOT_ID = 3


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


class TestTrackedSlotsConditional(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.client = self.app.test_client()

        players = [
            {'slot_id': SLOT_ID, 'name': 'Link', 'game': 'Zelda', 'total_locations': 216},
            {'slot_id': 4, 'name': 'Samus', 'game': 'Metroid', 'total_locations': 100},
        ]
        session = Session()
        try:
            user = User(discord_id='user_a', discord_username='UserA')
            other = User(discord_id='user_b', discord_username='UserB')
            session.add_all([user, other])
            session.flush()
            self.user_id = user.id
            self.other_user_id = other.id

            room = TrackedRoom(room_id=ROOM_UUID, cached_players_json=json.dumps(players))
            session.add(room)
            session.flush()
            self.room_db_id = room.id

            session.add_all([
                UserRoomSubscription(user_id=user.id, room_id=room.id, alias='Mine'),
                UserRoomSubscription(user_id=other.id, room_id=room.id, alias='Theirs'),
            ])
            session.flush()
            session.add_all([
                UserTrackedSlot(user_id=user.id, room_id=room.id, slot_id=SLOT_ID),
                UserTrackedSlot(user_id=other.id, room_id=room.id, slot_id=4),
            ])
            session.commit()
        finally:
            Session.remove()

        self.token = _make_token(self.app, self.user_id)

    def tearDown(self):
        Session.remove()
        engine.dispose()
        _remove_test_db()

    def _get(self, if_none_match=None, token=None):
        headers = {'Authorization': f'Bearer {token or self.token}'}
        if if_none_match is not None:
            headers['If-None-Match'] = if_none_match
        return self.client.get('/users/me/tracked-slots', headers=headers)

    def _first_etag(self):
        r = self._get()
        self.assertEqual(r.status_code, 200)
        return r.headers['ETag']

    # ------------------------------------------------------------------
    # 200 responses
    # ------------------------------------------------------------------

    def test_a_plain_request_gets_the_body_an_etag_and_revalidate_headers(self):
        """Old apps send no If-None-Match: they must keep getting the full body."""
        r = self._get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()[0]['tracked_slots'][0]['slot_id'], SLOT_ID)
        self.assertTrue(r.headers['ETag'].startswith('"'))
        cache_control = r.headers['Cache-Control']
        self.assertIn('private', cache_control)
        self.assertIn('no-cache', cache_control)

    def test_the_etag_is_stable_while_nothing_changes(self):
        self.assertEqual(self._first_etag(), self._first_etag())

    # ------------------------------------------------------------------
    # 304 responses
    # ------------------------------------------------------------------

    def test_the_current_etag_gets_304_with_no_body(self):
        etag = self._first_etag()

        r = self._get(if_none_match=etag)
        self.assertEqual(r.status_code, 304)
        self.assertEqual(r.get_data(), b'')
        self.assertEqual(r.headers['ETag'], etag)

    def test_the_weak_form_nginx_produces_still_matches(self):
        """nginx turns a strong ETag weak when it gzips, so the app sends W/"..." back."""
        etag = self._first_etag()

        r = self._get(if_none_match='W/' + etag)
        self.assertEqual(r.status_code, 304)

    # ------------------------------------------------------------------
    # Changes must always come through
    # ------------------------------------------------------------------

    def test_a_slot_setting_change_gets_a_new_body(self):
        etag = self._first_etag()
        session = Session()
        try:
            slot = session.query(UserTrackedSlot).filter_by(user_id=self.user_id, slot_id=SLOT_ID).one()
            slot.notify_hints = not slot.notify_hints
            session.commit()
        finally:
            Session.remove()

        r = self._get(if_none_match=etag)
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.headers['ETag'], etag)

    def test_a_room_change_gets_a_new_body(self):
        etag = self._first_etag()
        session = Session()
        try:
            room = session.query(TrackedRoom).filter_by(id=self.room_db_id).one()
            players = json.loads(room.cached_players_json)
            players[0]['is_finished'] = True
            room.cached_players_json = json.dumps(players)
            session.commit()
        finally:
            Session.remove()

        r = self._get(if_none_match=etag)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()[0]['tracked_slots'][0]['is_finished'])

    def test_an_unknown_etag_gets_the_body(self):
        r = self._get(if_none_match='"not-a-real-etag"')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()), 1)

    def test_another_users_etag_does_not_get_304(self):
        """The app's cache is keyed by URL, so after a sign-in switch it sends the last user's tag."""
        etag = self._first_etag()
        other_token = _make_token(self.app, self.other_user_id)

        r = self._get(if_none_match=etag, token=other_token)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()[0]['room_alias'], 'Theirs')

    def test_sign_in_is_still_required(self):
        r = self.client.get('/users/me/tracked-slots', headers={'If-None-Match': '"x"'})
        self.assertEqual(r.status_code, 401)


if __name__ == '__main__':
    unittest.main()
