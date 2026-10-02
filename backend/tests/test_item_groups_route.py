"""
Tests for the item-group and slot autocomplete routes staying off the cache scan.

Each of these routes used to run a "self-heal" check first: up to three
queries over datapackage_cache filtered on lower(game), which no index serves,
so every History item tap scanned the whole multi-GB table (about 10 s in
prod). The poller's 15-minute cache check already heals the same problems by
checksum, so the routes now only read. See #401.
"""
import json
import os
import unittest
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt as pyjwt
from sqlalchemy import event

# Set up test DB and config before importing the app
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_item_groups_route.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='  # Valid Fernet key

# Import through `app.*` only, never `backend.app.*` -- see the note in
# test_slot_track_mode.py.
from app import create_app, Session, engine
from app.models import Base, User, TrackedRoom, DatapackageCache

GAME = 'Ocarina of Time'
CHECKSUM = 'oot-checksum-1'
GROUPS = {'Bottles': ['Bottle', 'Bottle with Milk'], 'Everything': ['Bottle', 'Kokiri Sword']}


def _remove_test_db():
    for suffix in ('', '-wal', '-shm'):
        path = f"{TEST_DB_PATH}{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


class ItemGroupsRouteTest(unittest.TestCase):
    def setUp(self):
        # A request must never fetch a datapackage itself. If one tries, fail
        # loudly instead of reaching archipelago.gg.
        network = patch('requests.get', side_effect=AssertionError('request fetched over the network'))
        network.start()
        self.addCleanup(network.stop)

        self.app = create_app()
        self.app_context = self.app.app_context()
        self.app_context.push()

        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)

        self.session = Session()
        user = User(is_guest=True, guest_uuid=str(uuid_lib.uuid4()))
        self.session.add(user)
        room = TrackedRoom(
            room_id='room-uuid-1',
            game_checksums_json=json.dumps({GAME: CHECKSUM}),
            cached_players_json=json.dumps([{'slot_id': 1, 'name': 'Link', 'game': GAME}]),
        )
        self.session.add(room)
        self.session.commit()
        self.user_id = user.id
        self.room_id = room.id

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

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def cache(self, entity_type, entity_id, entity_name, checksum=CHECKSUM):
        self.session.add(DatapackageCache(
            game=GAME, checksum=checksum, entity_type=entity_type,
            entity_id=entity_id, entity_name=entity_name,
        ))
        self.session.commit()

    def cached_package(self, marker='_completed_v2'):
        self.cache('_metadata', 0, marker)
        self.cache('item', 1, 'Bottle')
        self.cache('item', 2, 'Kokiri Sword')
        self.cache('location', 3, 'Deku Tree Chest')
        self.cache('item_group', -1, 'Bottles')
        self.cache('item_group', -2, 'Everything')
        self.cache('item_name_groups_json', 0, json.dumps(GROUPS))

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

    def get(self, path):
        self.statements.clear()
        return self.app.test_client().get(path, headers=self.auth())

    def cache_scans(self):
        """Statements that filter on lower(game), which no index can serve."""
        return [s for s in self.statements if 'lower(datapackage_cache.game)' in s]

    def cache_rows(self):
        self.session.expire_all()
        return self.session.query(DatapackageCache).filter_by(checksum=CHECKSUM).count()

    def test_item_groups_answer_without_scanning_the_cache(self):
        self.cached_package()

        resp = self.get(f'/games/{GAME}/items/bottle/groups?room_db_id={self.room_id}')

        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json(), ['Bottles', 'Everything'])
        self.assertEqual(self.cache_scans(), [])

    def test_slot_items_answer_without_scanning_the_cache(self):
        self.cached_package()

        resp = self.get(f'/rooms/{self.room_id}/slots/1/items')

        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(
            [i['name'] for i in resp.get_json()],
            ['Bottle', 'Bottles', 'Everything', 'Kokiri Sword'],
        )
        self.assertEqual(self.cache_scans(), [])

    def test_slot_locations_answer_without_scanning_the_cache(self):
        self.cached_package()

        resp = self.get(f'/rooms/{self.room_id}/slots/1/locations')

        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual([i['name'] for i in resp.get_json()], ['Deku Tree Chest'])
        self.assertEqual(self.cache_scans(), [])

    def test_a_request_leaves_an_outdated_cache_to_the_poller(self):
        # A legacy `_completed` marker used to make the request delete the
        # package and re-download it inline. The poller's cache check owns
        # that now; the request answers from what is cached.
        self.cached_package(marker='_completed')
        rows_before = self.cache_rows()

        resp = self.get(f'/games/{GAME}/items/bottle/groups?room_db_id={self.room_id}')

        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json(), ['Bottles', 'Everything'])
        self.assertEqual(self.cache_rows(), rows_before)


if __name__ == '__main__':
    unittest.main()
