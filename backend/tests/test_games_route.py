"""
Tests for GET /games: signed-in only, cheap per call, and cached.

It used to run SELECT DISTINCT game over datapackage_cache with no login
check. Postgres has no loose index scan, so that read one index entry per
cached row: 14.8 s and ~470 MB of buffers on prod for ~2,400 names, callable
by anyone. The route now walks the game index one game at a time and holds
the answer for a few minutes. See #439.
"""
import os
import unittest
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from sqlalchemy import event

# Set up test DB and config before importing the app
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_games_route.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='  # Valid Fernet key

# Import through `app.*` only, never `backend.app.*` -- see the note in
# test_slot_track_mode.py.
from app import create_app, Session, engine
from app.models import Base, User, DatapackageCache
from app.routes import game_routes


def _remove_test_db():
    for suffix in ('', '-wal', '-shm'):
        path = f"{TEST_DB_PATH}{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


class GamesRouteTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app_context = self.app.app_context()
        self.app_context.push()

        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)

        # The cache is module state; start every test cold.
        self._clear_games_cache()
        self.addCleanup(self._clear_games_cache)

        self.session = Session()
        user = User(is_guest=True, guest_uuid=str(uuid_lib.uuid4()))
        self.session.add(user)
        self.session.commit()
        self.user_id = user.id

        self.statements = []
        event.listen(engine, 'before_cursor_execute', self._record)
        self.addCleanup(event.remove, engine, 'before_cursor_execute', self._record)

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

    @staticmethod
    def _clear_games_cache():
        game_routes._games_cache['games'] = None
        game_routes._games_cache['expires_at'] = 0.0

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def cache_game(self, game, rows=3, checksum=None):
        checksum = checksum or f'{game}-checksum'
        for i in range(rows):
            self.session.add(DatapackageCache(
                game=game, checksum=checksum, entity_type='item',
                entity_id=i, entity_name=f'{game} item {i}',
            ))
        self.session.commit()

    def auth(self):
        token = pyjwt.encode(
            {
                'user_id': self.user_id,
                'iat': datetime.now(timezone.utc),
                'exp': datetime.now(timezone.utc) + timedelta(days=1),
                'jti': str(uuid_lib.uuid4()),
                'type': 'access',
            },
            self.app.config['SECRET_KEY'],
            algorithm='HS256',
        )
        return {'Authorization': f'Bearer {token}'}

    def get_games(self, headers=None):
        self.statements.clear()
        return self.app.test_client().get('/games', headers=self.auth() if headers is None else headers)

    def cache_reads(self):
        return [s for s in self.statements if 'datapackage_cache' in s]

    def test_requires_a_signed_in_user(self):
        self.cache_game('Ocarina of Time')

        resp = self.get_games(headers={})

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(self.cache_reads(), [], 'an anonymous call must not touch the cache')

    def test_lists_each_game_once_in_order(self):
        self.cache_game('Super Metroid', rows=5)
        self.cache_game('A Link to the Past', rows=2)
        self.cache_game('Ocarina of Time', rows=4)
        # A second checksum for the same game is a second datapackage version.
        self.cache_game('Ocarina of Time', rows=4, checksum='oot-older-checksum')

        resp = self.get_games()

        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json(), ['A Link to the Past', 'Ocarina of Time', 'Super Metroid'])

    def test_skips_blank_game_names(self):
        self.cache_game('')
        self.cache_game('Ocarina of Time')

        resp = self.get_games()

        self.assertEqual(resp.get_json(), ['Ocarina of Time'])

    def test_empty_cache_returns_an_empty_list(self):
        resp = self.get_games()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), [])

    def test_walks_the_game_index_instead_of_a_distinct_scan(self):
        self.cache_game('Ocarina of Time')

        self.get_games()

        reads = self.cache_reads()
        self.assertEqual(len(reads), 1, reads)
        self.assertIn('WITH RECURSIVE', reads[0])
        self.assertNotIn('DISTINCT', reads[0].upper())

    def test_second_call_is_served_from_memory(self):
        self.cache_game('Ocarina of Time')
        self.get_games()

        self.cache_game('Super Metroid')
        resp = self.get_games()

        self.assertEqual(resp.get_json(), ['Ocarina of Time'])
        self.assertEqual(self.cache_reads(), [])

    def test_expired_cache_picks_up_new_games(self):
        self.cache_game('Ocarina of Time')
        self.get_games()

        self.cache_game('Super Metroid')
        game_routes._games_cache['expires_at'] = 0.0
        resp = self.get_games()

        self.assertEqual(resp.get_json(), ['Ocarina of Time', 'Super Metroid'])


if __name__ == '__main__':
    unittest.main()
