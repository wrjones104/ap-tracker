import os
import sys
import unittest
import json

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_datapackage_checksum.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import Base, User, DatapackageCache, TrackedRoom
from app.utils import generate_negative_id


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


class TestDatapackageByChecksum(unittest.TestCase):
    """
    Covers /datapackage/checksum/<checksum>, the endpoint the text client uses to turn
    PrintJSON ids into names.

    The client caches every 200 from here on disk forever, so what this route serves is
    effectively permanent for a given checksum. That makes the shape of the response --
    which entity types are in it, and what a cache miss looks like -- worth pinning.
    """

    def setUp(self):
        self.app = create_app()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.client = self.app.test_client()
        session = Session()
        try:
            self.user = User(discord_id='user_a', discord_username='UserA')
            session.add(self.user)
            session.commit()
            self.token = _make_token(self.app, self.user.id)
        finally:
            Session.remove()

    def tearDown(self):
        Session.remove()
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def _auth(self):
        return {'Authorization': f'Bearer {self.token}'}

    def _cache(self, checksum, game, entries):
        session = Session()
        try:
            for entity_type, entity_id, entity_name in entries:
                session.add(DatapackageCache(
                    game=game,
                    checksum=checksum,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    entity_name=entity_name,
                ))
            session.commit()
        finally:
            Session.remove()

    # ------------------------------------------------------------------

    def test_serves_item_and_location_tables(self):
        self._cache('chk_shapez', 'shapez', [
            ('item', 2322561, 'Belt'),
            ('item', 2009136, 'Cutter'),
            ('location', 12546, 'Level 5 Reward'),
            ('_metadata', 0, '_completed_v2'),
        ])

        res = self.client.get('/datapackage/checksum/chk_shapez', headers=self._auth())
        self.assertEqual(res.status_code, 200)

        body = json.loads(res.data)
        self.assertEqual(body['checksum'], 'chk_shapez')
        self.assertEqual(body['game'], 'shapez')
        self.assertEqual(body['items'], {'2322561': 'Belt', '2009136': 'Cutter'})
        self.assertEqual(body['locations'], {'12546': 'Level 5 Reward'})

    def test_group_rows_are_excluded(self):
        """
        Groups carry synthetic negative ids from generate_negative_id(), which share an
        id space with real negative ids -- Archipelago's generic world uses location -1
        and -2. PrintJSON never names a group by id, so including them could only ever
        shadow a real lookup.
        """
        group_id = generate_negative_id('item_group', 'Belts')
        self._cache('chk_shapez', 'shapez', [
            ('item', 2322561, 'Belt'),
            ('item_group', group_id, 'Belts'),
            ('location_group', generate_negative_id('location_group', 'Levels'), 'Levels'),
            ('item_name_groups_json', 0, json.dumps({'Belts': ['Belt']})),
        ])

        res = self.client.get('/datapackage/checksum/chk_shapez', headers=self._auth())
        self.assertEqual(res.status_code, 200)

        body = json.loads(res.data)
        self.assertEqual(body['items'], {'2322561': 'Belt'})
        self.assertEqual(body['locations'], {})
        self.assertNotIn(str(group_id), body['items'])

    def test_empty_datapackage_answers_200_not_404(self):
        """
        A game whose datapackage is genuinely empty caches only a metadata marker.
        Answering 200-with-nothing lets the client record "nothing to resolve here"
        permanently; a 404 would send it back to re-ask on every single connect.

        Both markers are covered because the writers emit '_empty_datapackage' for a
        genuinely empty package and '_completed_v2' for one that had entries, and the
        endpoint must not start caring which it sees.
        """
        for marker in ('_empty_datapackage', '_completed_v2'):
            with self.subTest(marker=marker):
                checksum = 'chk' + marker
                self._cache(checksum, 'Archipelago', [('_metadata', 0, marker)])

                res = self.client.get(
                    '/datapackage/checksum/' + checksum, headers=self._auth())
                self.assertEqual(res.status_code, 200)

                body = json.loads(res.data)
                self.assertEqual(body['items'], {})
                self.assertEqual(body['locations'], {})

    def test_uncached_checksum_is_404(self):
        res = self.client.get('/datapackage/checksum/chk_unknown', headers=self._auth())
        self.assertEqual(res.status_code, 404)

    def test_requires_authentication(self):
        self._cache('chk_shapez', 'shapez', [('item', 1, 'Belt')])

        res = self.client.get('/datapackage/checksum/chk_shapez')
        self.assertEqual(res.status_code, 401)

    def test_response_is_immutable_and_revalidates_with_etag(self):
        """
        A checksum is a content hash, so its tables can never change under a client.
        The immutable Cache-Control and the matching ETag are what let the app keep a
        package on disk indefinitely instead of refetching it on every connect.
        """
        self._cache('chk_shapez', 'shapez', [('item', 1, 'Belt')])

        res = self.client.get('/datapackage/checksum/chk_shapez', headers=self._auth())
        self.assertEqual(res.status_code, 200)
        self.assertIn('immutable', res.headers.get('Cache-Control', ''))
        # Authenticated route: shared caches must not retain the body.
        self.assertIn('private', res.headers.get('Cache-Control', ''))

        etag = res.headers.get('ETag')
        self.assertIsNotNone(etag)

        headers = self._auth()
        headers['If-None-Match'] = etag
        cached = self.client.get('/datapackage/checksum/chk_shapez', headers=headers)
        self.assertEqual(cached.status_code, 304)

    def test_identical_ids_in_different_games_stay_separate(self):
        """
        Ids are only unique within one game's datapackage. Addressing by checksum is
        what keeps two games that both use id 40 from resolving to each other's names.
        """
        self._cache('chk_a', 'Game A', [('item', 40, 'Item X'), ('location', 40, 'Boss Chest')])
        self._cache('chk_b', 'Game B', [('item', 40, 'Totally Different'), ('location', 40, 'Minigame Prize')])

        a = json.loads(self.client.get('/datapackage/checksum/chk_a', headers=self._auth()).data)
        b = json.loads(self.client.get('/datapackage/checksum/chk_b', headers=self._auth()).data)

        self.assertEqual(a['items']['40'], 'Item X')
        self.assertEqual(b['items']['40'], 'Totally Different')
        self.assertEqual(a['locations']['40'], 'Boss Chest')
        self.assertEqual(b['locations']['40'], 'Minigame Prize')


    def test_legacy_room_route_emits_generic_checksum(self):
        """
        The room-scoped route is the fallback for a client whose backend cannot serve
        per-checksum packages. It has to carry generic_checksum too, or Cheat Console
        and Server render as -1 and -2 on exactly the path that exists to avoid raw ids.
        """
        session = Session()
        try:
            room = TrackedRoom(
                room_id='room-uuid-1',
                cached_players_json=json.dumps([
                    {'slot_id': 1, 'name': 'Hyper', 'game': 'shapez'},
                ]),
                game_checksums_json=json.dumps({
                    'shapez': 'chk_shapez',
                    'Archipelago': 'chk_generic',
                }),
            )
            session.add(room)
            session.commit()
            room_db_id = room.id
        finally:
            Session.remove()

        self._cache('chk_generic', 'Archipelago', [('location', -1, 'Cheat Console')])

        res = self.client.get(
            f'/rooms/{room_db_id}/datapackage', headers=self._auth())
        self.assertEqual(res.status_code, 200)

        body = json.loads(res.data)
        self.assertEqual(body['generic_checksum'], 'chk_generic')
        self.assertEqual(body['locations']['chk_generic_-1'], 'Cheat Console')


if __name__ == '__main__':
    unittest.main()
