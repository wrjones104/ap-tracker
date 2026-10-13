import os
import sys
import unittest
import json

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_threshold_groups_batch.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import event

from app import create_app, Session, engine
from app.models import (
    Base, User, TrackedRoom, UserRoomSubscription, UserTrackedSlot, ThresholdGroup,
    ThresholdGroupItem, DatapackageCache, SlotItemCount
)

ROOM_A = 'room-uuid-a'
ROOM_B = 'room-uuid-b'
CHECKSUM_ZELDA = 'chk_zelda'
CHECKSUM_METROID = 'chk_metroid'

# Item id -> name, as the datapackage cache would hold them.
ZELDA_ITEMS = {101: 'Fire Essence', 102: 'Water Essence', 103: 'Earth Essence', 104: 'Wooden Sword'}
METROID_ITEMS = {201: 'Missile', 202: 'Energy Tank'}


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


class TestThresholdGroupsBatch(unittest.TestCase):
    """
    Covers GET /users/me/threshold-groups (#418): every tracked slot's milestone groups in one
    response, replacing the Milestones widget's one-request-per-slot refresh.

    Room A plays Zelda in slots 1 and 2 and Metroid in slot 3; room B plays Zelda in slot 1.
    The user tracks all four. Another user tracks room A slot 1 with a group of their own.
    """

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
            self.user_id = user.id
            self.other_user_id = other.id

            room_a = TrackedRoom(
                room_id=ROOM_A,
                game_checksums_json=json.dumps({'Zelda': CHECKSUM_ZELDA, 'Metroid': CHECKSUM_METROID}),
                cached_players_json=json.dumps([
                    {'slot_id': 1, 'name': 'Link', 'game': 'Zelda'},
                    {'slot_id': 2, 'name': 'Zelda', 'game': 'Zelda'},
                    {'slot_id': 3, 'name': 'Samus', 'game': 'Metroid'},
                ])
            )
            room_b = TrackedRoom(
                room_id=ROOM_B,
                game_checksums_json=json.dumps({'Zelda': CHECKSUM_ZELDA}),
                cached_players_json=json.dumps([{'slot_id': 1, 'name': 'Link', 'game': 'Zelda'}])
            )
            session.add_all([room_a, room_b])
            session.flush()
            self.room_a = room_a.id
            self.room_b = room_b.id

            # A tracked slot has a composite foreign key to its subscription.
            session.add_all([
                UserRoomSubscription(user_id=user.id, room_id=room_a.id, alias='A'),
                UserRoomSubscription(user_id=user.id, room_id=room_b.id, alias='B'),
                UserRoomSubscription(user_id=other.id, room_id=room_a.id, alias='Theirs'),
            ])
            session.flush()

            self.tracked = {}
            for room_db_id, slot_id in [(room_a.id, 1), (room_a.id, 2), (room_a.id, 3), (room_b.id, 1)]:
                ts = UserTrackedSlot(user_id=user.id, room_id=room_db_id, slot_id=slot_id)
                session.add(ts)
                session.flush()
                self.tracked[(room_db_id, slot_id)] = ts.id
            other_slot = UserTrackedSlot(user_id=other.id, room_id=room_a.id, slot_id=1)
            session.add(other_slot)
            session.flush()
            self.other_tracked_slot_id = other_slot.id

            for checksum, game, items in [
                (CHECKSUM_ZELDA, 'Zelda', ZELDA_ITEMS), (CHECKSUM_METROID, 'Metroid', METROID_ITEMS)
            ]:
                for item_id, name in items.items():
                    session.add(DatapackageCache(
                        game=game, checksum=checksum, entity_type='item',
                        entity_id=item_id, entity_name=name
                    ))
            session.add(DatapackageCache(
                game='Zelda', checksum=CHECKSUM_ZELDA, entity_type='item_name_groups_json', entity_id=0,
                entity_name=json.dumps({'Essences': ['Fire Essence', 'Water Essence', 'Earth Essence']})
            ))

            session.commit()
            self.token = _make_token(self.app, self.user_id)
        finally:
            Session.remove()

        self.statements = []

    def tearDown(self):
        Session.remove()
        engine.dispose()
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_group(self, tracked_slot_id, items, name='Milestone', is_triggered=False):
        """items: list of (item_name, quantity, is_group)."""
        session = Session()
        try:
            group = ThresholdGroup(user_tracked_slot_id=tracked_slot_id, name=name, is_triggered=is_triggered)
            session.add(group)
            session.flush()
            for item_name, quantity, is_group in items:
                session.add(ThresholdGroupItem(
                    group_id=group.id, item_name=item_name, quantity=quantity, is_group=is_group
                ))
            session.commit()
            return group.id
        finally:
            Session.remove()

    def _add_counts(self, room_uuid, slot_id, counts):
        session = Session()
        try:
            for item_id, count in counts.items():
                session.add(SlotItemCount(room_id=room_uuid, slot_id=slot_id, item_id=item_id, count=count))
            session.commit()
        finally:
            Session.remove()

    def _get_batch(self, token=None):
        r = self.client.get(
            '/users/me/threshold-groups',
            headers={'Authorization': f'Bearer {token or self.token}'}
        )
        self.assertEqual(r.status_code, 200)
        return r.get_json()

    def _by_slot(self, payload):
        return {(e['room_db_id'], e['slot_id']): e['groups'] for e in payload}

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def _seed_typical(self):
        self._add_counts(ROOM_A, 1, {101: 1, 102: 2, 104: 1})
        self._add_counts(ROOM_A, 2, {103: 1})
        self._add_counts(ROOM_A, 3, {201: 4})
        self._add_counts(ROOM_B, 1, {101: 5})
        self._add_group(self.tracked[(self.room_a, 1)], [('Essences', 4, True), ('Wooden Sword', 1, False)], name='First')
        self._add_group(self.tracked[(self.room_a, 1)], [('Wooden Sword', 2, False)], name='Second', is_triggered=True)
        self._add_group(self.tracked[(self.room_a, 2)], [('Essences', 3, True)])
        self._add_group(self.tracked[(self.room_a, 3)], [('Missile', 5, False), ('Energy Tank', 1, False)])
        self._add_group(self.tracked[(self.room_b, 1)], [('Essences', 3, True)])
        # Another user's group on a slot this user also tracks.
        self._add_group(self.other_tracked_slot_id, [('Fire Essence', 1, False)], name='Not mine')

    # ------------------------------------------------------------------
    # Shape and scope
    # ------------------------------------------------------------------

    def test_requires_login(self):
        r = self.client.get('/users/me/threshold-groups')
        self.assertEqual(r.status_code, 401)

    def test_no_tracked_slots_returns_empty_list(self):
        other_token = _make_token(self.app, self.other_user_id)
        session = Session()
        try:
            session.query(UserTrackedSlot).filter_by(user_id=self.other_user_id).delete()
            session.commit()
        finally:
            Session.remove()
        self.assertEqual(self._get_batch(other_token), [])

    def test_lists_every_tracked_slot_including_ones_without_groups(self):
        self._add_group(self.tracked[(self.room_a, 1)], [('Wooden Sword', 1, False)])

        by_slot = self._by_slot(self._get_batch())
        self.assertEqual(
            set(by_slot),
            {(self.room_a, 1), (self.room_a, 2), (self.room_a, 3), (self.room_b, 1)}
        )
        self.assertEqual(len(by_slot[(self.room_a, 1)]), 1)
        self.assertEqual(by_slot[(self.room_a, 2)], [])
        self.assertEqual(by_slot[(self.room_b, 1)], [])

    def test_other_users_groups_are_not_included(self):
        self._seed_typical()

        names = [g['name'] for groups in self._by_slot(self._get_batch()).values() for g in groups]
        self.assertNotIn('Not mine', names)
        self.assertEqual(sorted(names), ['First', 'Milestone', 'Milestone', 'Milestone', 'Second'])

    def test_each_slot_matches_the_per_slot_endpoint(self):
        """The app swaps per-slot fetches for this one, so the group payloads must be identical."""
        self._seed_typical()

        by_slot = self._by_slot(self._get_batch())
        for (room_db_id, slot_id), groups in by_slot.items():
            r = self.client.get(
                f'/rooms/{room_db_id}/slots/{slot_id}/threshold-groups',
                headers={'Authorization': f'Bearer {self.token}'}
            )
            self.assertEqual(r.status_code, 200)
            single = sorted(r.get_json(), key=lambda g: g['id'])
            self.assertEqual(groups, single, f'room {room_db_id} slot {slot_id}')

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    def test_progress_is_counted_per_slot(self):
        """Two slots of the same game share a datapackage but never each other's counts."""
        self._seed_typical()

        by_slot = self._by_slot(self._get_batch())

        def acquired(key, group_index=0):
            return {i['item_name']: i['acquired'] for i in by_slot[key][group_index]['items']}

        self.assertEqual(acquired((self.room_a, 1)), {'Essences': 3, 'Wooden Sword': 1})
        self.assertEqual(acquired((self.room_a, 2)), {'Essences': 1})
        self.assertEqual(acquired((self.room_a, 3)), {'Missile': 4, 'Energy Tank': 0})
        self.assertEqual(acquired((self.room_b, 1)), {'Essences': 5})

    def test_unresolvable_slot_degrades_to_null_without_affecting_others(self):
        self._seed_typical()
        session = Session()
        try:
            room = session.query(TrackedRoom).filter_by(id=self.room_b).first()
            room.game_checksums_json = json.dumps({})
            session.commit()
        finally:
            Session.remove()

        by_slot = self._by_slot(self._get_batch())
        self.assertIsNone(by_slot[(self.room_b, 1)][0]['items'][0]['acquired'])
        self.assertEqual(by_slot[(self.room_a, 2)][0]['items'][0]['acquired'], 1)

    def test_each_games_datapackage_is_loaded_once(self):
        """Three Zelda slots and one Metroid slot: two item-map loads, not four."""
        self._seed_typical()

        event.listen(engine, 'before_cursor_execute', self._record)
        self.addCleanup(event.remove, engine, 'before_cursor_execute', self._record)
        self._get_batch()

        item_map_loads = [
            s for s in self.statements
            if 'datapackage_cache.entity_id' in s and 'datapackage_cache.entity_type' in s
        ]
        self.assertEqual(len(item_map_loads), 2)

    def test_query_count_does_not_grow_with_group_less_slots(self):
        """Slots without groups cost no queries beyond the shared ones."""
        event.listen(engine, 'before_cursor_execute', self._record)
        self.addCleanup(event.remove, engine, 'before_cursor_execute', self._record)
        self._get_batch()
        baseline = len(self.statements)

        session = Session()
        try:
            for slot_id in range(10, 30):
                session.add(UserTrackedSlot(user_id=self.user_id, room_id=self.room_a, slot_id=slot_id))
            session.commit()
        finally:
            Session.remove()

        self.statements.clear()
        payload = self._get_batch()
        self.assertEqual(len(payload), 24)
        self.assertEqual(len(self.statements), baseline)


if __name__ == '__main__':
    unittest.main()
