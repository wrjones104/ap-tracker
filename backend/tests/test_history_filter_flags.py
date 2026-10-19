"""
Tests for GET /history/filter-flags (#464).

The app stores isIgnored and isWhitelisted with each item when it first downloads it, so a rule
added or removed later never reached the items already on the phone. After a rule change the app
asks this route which of its items the rules match now, and re-flags its cache.
"""
import json
import os
import sys
import unittest

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_history_filter_flags.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import (
    Base, User, TrackedRoom, UserRoomSubscription, UserTrackedSlot, DatapackageCache,
    NotifiedItem, UserIgnoreItem, UserWhitelistItem
)

ROOM_UUID = 'room-uuid-flags'
ZELDA, METROID = 'Zelda', 'Metroid'
CHK_ZELDA, CHK_METROID = 'chk_zelda', 'chk_metroid'

ZELDA_ITEMS = {101: 'Rupee', 102: 'Heart Container', 103: 'Fire Essence'}
METROID_ITEMS = {201: 'Missile', 202: 'Energy Tank'}

# (slot, item_id, copies). Slot 3 plays Zelda but nobody here tracks it.
RECEIVED = [(1, 101, 3), (1, 102, 1), (1, 103, 1), (2, 201, 2), (2, 202, 1), (3, 101, 2)]


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


class TestHistoryFilterFlags(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.client = self.app.test_client()

        session = Session()
        try:
            user = User(discord_id='user_a', discord_username='UserA')
            other = User(discord_id='user_b', discord_username='UserB')
            session.add_all([user, other])
            session.flush()
            self.user_id, self.other_id = user.id, other.id

            room = TrackedRoom(
                room_id=ROOM_UUID,
                game_checksums_json=json.dumps({ZELDA: CHK_ZELDA, METROID: CHK_METROID}),
                cached_players_json=json.dumps([
                    {'slot_id': 1, 'name': 'Link', 'game': ZELDA},
                    {'slot_id': 2, 'name': 'Samus', 'game': METROID},
                    {'slot_id': 3, 'name': 'Zelda', 'game': ZELDA},
                ])
            )
            session.add(room)
            session.flush()

            session.add_all([
                UserRoomSubscription(user_id=user.id, room_id=room.id, alias='Mine'),
                UserRoomSubscription(user_id=other.id, room_id=room.id, alias='Theirs'),
            ])
            session.flush()
            session.add_all([
                UserTrackedSlot(user_id=user.id, room_id=room.id, slot_id=1),
                UserTrackedSlot(user_id=user.id, room_id=room.id, slot_id=2),
                UserTrackedSlot(user_id=other.id, room_id=room.id, slot_id=1),
            ])

            for checksum, game, items in [(CHK_ZELDA, ZELDA, ZELDA_ITEMS), (CHK_METROID, METROID, METROID_ITEMS)]:
                for item_id, name in items.items():
                    session.add(DatapackageCache(
                        game=game, checksum=checksum, entity_type='item', entity_id=item_id, entity_name=name
                    ))
            session.add(DatapackageCache(
                game=ZELDA, checksum=CHK_ZELDA, entity_type='item_name_groups_json', entity_id=0,
                entity_name=json.dumps({'Essences': ['Fire Essence']})
            ))

            self.ids = {}
            index = 0
            for slot, item_id, copies in RECEIVED:
                for _ in range(copies):
                    index += 1
                    row = NotifiedItem(
                        room_id=ROOM_UUID, receiving_slot_id=slot, sending_slot_id=2,
                        item_id=item_id, location_id=index, item_index=index, item_flags=0
                    )
                    session.add(row)
                    session.flush()
                    self.ids.setdefault((slot, item_id), []).append(row.id)
            session.commit()
        finally:
            Session.remove()

        self.token = _make_token(self.app, self.user_id)

    def tearDown(self):
        Session.remove()
        engine.dispose()
        _remove_test_db()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _rule(self, model, item_name, game_name=None, is_group=False, user_id=None):
        session = Session()
        try:
            session.add(model(
                user_id=user_id or self.user_id, item_name=item_name, game_name=game_name, is_group=is_group
            ))
            session.commit()
        finally:
            Session.remove()

    def _flags(self, token=None):
        r = self.client.get('/history/filter-flags', headers={'Authorization': f'Bearer {token or self.token}'})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        return set(body['ignored_ids']), set(body['whitelisted_ids'])

    def _ids(self, *keys):
        return {i for key in keys for i in self.ids[key]}

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def test_no_rules_means_nothing_is_flagged(self):
        self.assertEqual(self._flags(), (set(), set()))

    def test_a_rule_added_after_the_items_flags_every_copy(self):
        """The point of the route: rules apply to items that arrived before them."""
        self._rule(UserIgnoreItem, 'Rupee', ZELDA)

        ignored, whitelisted = self._flags()
        self.assertEqual(ignored, self._ids((1, 101)))
        self.assertEqual(whitelisted, set())

    def test_items_of_untracked_slots_are_left_out(self):
        self._rule(UserIgnoreItem, 'Rupee', ZELDA)

        ignored, _ = self._flags()
        self.assertFalse(ignored & self._ids((3, 101)))

    def test_wildcards_and_any_game_rules_match(self):
        self._rule(UserIgnoreItem, '*container')

        ignored, _ = self._flags()
        self.assertEqual(ignored, self._ids((1, 102)))

    def test_a_group_rule_matches_its_members(self):
        self._rule(UserIgnoreItem, 'Essences', ZELDA, is_group=True)

        ignored, _ = self._flags()
        self.assertEqual(ignored, self._ids((1, 103)))

    def test_a_rule_for_another_game_does_not_match(self):
        self._rule(UserIgnoreItem, 'Missile', ZELDA)

        self.assertEqual(self._flags(), (set(), set()))

    def test_whitelist_beats_ignore(self):
        self._rule(UserIgnoreItem, '*')
        self._rule(UserWhitelistItem, 'Missile', METROID)

        ignored, whitelisted = self._flags()
        self.assertEqual(whitelisted, self._ids((2, 201)))
        self.assertEqual(ignored, self._ids((1, 101), (1, 102), (1, 103), (2, 202)))

    def test_another_users_rules_do_not_apply(self):
        self._rule(UserIgnoreItem, 'Rupee', ZELDA, user_id=self.other_id)

        self.assertEqual(self._flags(), (set(), set()))

    # ------------------------------------------------------------------
    # Agreement with the history routes
    # ------------------------------------------------------------------

    def _assert_agrees(self, items, ignored, whitelisted):
        for item in items:
            self.assertEqual(item['isIgnored'], item['id'] in ignored, item['itemName'])
            self.assertEqual(item['isWhitelisted'], item['id'] in whitelisted, item['itemName'])

    def test_flags_agree_with_what_the_history_routes_send(self):
        """Re-flagging must land on the same answer a fresh download would, from either route."""
        self._rule(UserIgnoreItem, '*')
        self._rule(UserIgnoreItem, 'Essences', ZELDA, is_group=True)
        self._rule(UserWhitelistItem, 'Rupee', ZELDA)

        ignored, whitelisted = self._flags()
        headers = {'Authorization': f'Bearer {self.token}'}

        r = self.client.get('/history/items?limit=100', headers=headers)
        self.assertEqual(r.status_code, 200)
        items = r.get_json()
        self.assertEqual(len(items), 8)
        self._assert_agrees(items, ignored, whitelisted)

        # The phone's stored history comes mostly from the delta sync.
        r = self.client.post('/history/sync', json={}, headers=headers)
        self.assertEqual(r.status_code, 200)
        synced = r.get_json()['new_items']
        self.assertEqual(len(synced), 8)
        self._assert_agrees(synced, ignored, whitelisted)

    # ------------------------------------------------------------------
    # Less common shapes
    # ------------------------------------------------------------------

    def _add_tracked_items(self, room_uuid, room_db_id, slot_id, item_ids, first_index):
        session = Session()
        try:
            session.add(UserTrackedSlot(user_id=self.user_id, room_id=room_db_id, slot_id=slot_id))
            ids = []
            for n, item_id in enumerate(item_ids):
                row = NotifiedItem(
                    room_id=room_uuid, receiving_slot_id=slot_id, sending_slot_id=1,
                    item_id=item_id, location_id=first_index + n, item_index=first_index + n, item_flags=0
                )
                session.add(row)
                session.flush()
                ids.append(row.id)
            session.commit()
            return set(ids)
        finally:
            Session.remove()

    def test_a_slot_with_no_known_game_matches_on_the_fallback_name(self):
        """No player entry, so no game or checksum: the name is "Item ID N", as the history routes send it."""
        session = Session()
        try:
            room_db_id = session.query(TrackedRoom).filter_by(room_id=ROOM_UUID).one().id
        finally:
            Session.remove()
        unknown_ids = self._add_tracked_items(ROOM_UUID, room_db_id, 9, [999, 999], first_index=500)
        self._rule(UserIgnoreItem, 'Item ID 999')

        ignored, _ = self._flags()
        self.assertEqual(ignored, unknown_ids)

    def test_items_in_every_tracked_room_are_covered(self):
        session = Session()
        try:
            room2 = TrackedRoom(
                room_id='room-uuid-two',
                game_checksums_json=json.dumps({METROID: CHK_METROID}),
                cached_players_json=json.dumps([{'slot_id': 1, 'name': 'Samus', 'game': METROID}])
            )
            session.add(room2)
            session.flush()
            session.add(UserRoomSubscription(user_id=self.user_id, room_id=room2.id, alias='Second'))
            session.commit()
            room2_db_id = room2.id
        finally:
            Session.remove()
        room2_ids = self._add_tracked_items('room-uuid-two', room2_db_id, 1, [201, 201], first_index=600)
        self._rule(UserIgnoreItem, 'Missile', METROID)

        ignored, _ = self._flags()
        self.assertEqual(ignored, self._ids((2, 201)) | room2_ids)

    def test_sign_in_is_required(self):
        self.assertEqual(self.client.get('/history/filter-flags').status_code, 401)


if __name__ == '__main__':
    unittest.main()
