import os
import sys
import unittest
import json

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_milestone_progress.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import (
    Base, User, TrackedRoom, UserTrackedSlot, ThresholdGroup, ThresholdGroupItem,
    DatapackageCache, SlotItemCount
)

ROOM_UUID = 'room-uuid-1'
CHECKSUM = 'chk_zelda'
GAME = 'Zelda'
SLOT_ID = 3

# Item id -> name, as the datapackage cache would hold them.
ITEMS = {
    101: 'Fire Essence',
    102: 'Water Essence',
    103: 'Earth Essence',
    104: 'Wooden Sword',
}


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


class TestMilestoneProgress(unittest.TestCase):
    """
    Covers the `acquired` counts returned by GET .../threshold-groups.

    Item-group requirements are the reason this exists: the Milestones widget tallies plain items
    from its local history, but it has no group membership data, so the server has to count those.
    """

    def setUp(self):
        self.app = create_app()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.client = self.app.test_client()
        session = Session()
        try:
            user = User(discord_id='user_a', discord_username='UserA')
            session.add(user)
            session.flush()
            self.user_id = user.id

            room = TrackedRoom(
                room_id=ROOM_UUID,
                game_checksums_json=json.dumps({GAME: CHECKSUM}),
                cached_players_json=json.dumps([{'slot_id': SLOT_ID, 'name': 'Link', 'game': GAME}])
            )
            session.add(room)
            session.flush()
            self.room_db_id = room.id

            slot = UserTrackedSlot(user_id=user.id, room_id=room.id, slot_id=SLOT_ID)
            session.add(slot)
            session.flush()
            self.tracked_slot_id = slot.id

            for item_id, name in ITEMS.items():
                session.add(DatapackageCache(
                    game=GAME, checksum=CHECKSUM, entity_type='item',
                    entity_id=item_id, entity_name=name
                ))
            session.add(DatapackageCache(
                game=GAME, checksum=CHECKSUM, entity_type='item_name_groups_json', entity_id=0,
                entity_name=json.dumps({
                    'Essences': ['Fire Essence', 'Water Essence', 'Earth Essence'],
                })
            ))

            session.commit()
            self.token = _make_token(self.app, self.user_id)
        finally:
            Session.remove()

    def tearDown(self):
        Session.remove()
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_counts(self, counts):
        """counts: {item_id: count} held by the tracked slot."""
        session = Session()
        try:
            for item_id, count in counts.items():
                session.add(SlotItemCount(
                    room_id=ROOM_UUID, slot_id=SLOT_ID, item_id=item_id, count=count
                ))
            session.commit()
        finally:
            Session.remove()

    def _add_group(self, items, name='Milestone', is_triggered=False):
        """items: list of (item_name, quantity, is_group)."""
        session = Session()
        try:
            group = ThresholdGroup(
                user_tracked_slot_id=self.tracked_slot_id, name=name, is_triggered=is_triggered
            )
            session.add(group)
            session.flush()
            for item_name, quantity, is_group in items:
                session.add(ThresholdGroupItem(
                    group_id=group.id, item_name=item_name, quantity=quantity, is_group=is_group
                ))
            session.commit()
        finally:
            Session.remove()

    def _get_groups(self, room_db_id=None, slot_id=None):
        r = self.client.get(
            f'/rooms/{room_db_id or self.room_db_id}/slots/{slot_id or SLOT_ID}/threshold-groups',
            headers={'Authorization': f'Bearer {self.token}'}
        )
        self.assertEqual(r.status_code, 200)
        return r.get_json()

    def _items_by_name(self, payload):
        return {i['item_name']: i for i in payload[0]['items']}

    # ------------------------------------------------------------------
    # Item groups
    # ------------------------------------------------------------------

    def test_group_requirement_sums_member_counts(self):
        self._add_counts({101: 1, 102: 2})
        self._add_group([('Essences', 4, True)])

        items = self._items_by_name(self._get_groups())
        self.assertEqual(items['Essences']['acquired'], 3)

    def test_group_requirement_ignores_non_member_counts(self):
        self._add_counts({101: 1, 104: 7})
        self._add_group([('Essences', 3, True)])

        items = self._items_by_name(self._get_groups())
        self.assertEqual(items['Essences']['acquired'], 1)

    def test_group_requirement_is_case_insensitive(self):
        self._add_counts({103: 2})
        self._add_group([('essences', 3, True)])

        items = self._items_by_name(self._get_groups())
        self.assertEqual(items['essences']['acquired'], 2)

    def test_group_with_no_members_held_reports_zero_not_null(self):
        self._add_group([('Essences', 3, True)])

        items = self._items_by_name(self._get_groups())
        self.assertEqual(items['Essences']['acquired'], 0)

    def test_unknown_group_reports_null(self):
        """A group the datapackage does not define is unknowable, not zero."""
        self._add_group([('Trinkets', 2, True)])

        items = self._items_by_name(self._get_groups())
        self.assertIsNone(items['Trinkets']['acquired'])

    # ------------------------------------------------------------------
    # Plain items
    # ------------------------------------------------------------------

    def test_plain_item_reports_its_own_count(self):
        self._add_counts({104: 2})
        self._add_group([('Wooden Sword', 3, False)])

        items = self._items_by_name(self._get_groups())
        self.assertEqual(items['Wooden Sword']['acquired'], 2)

    def test_unknown_item_reports_null(self):
        self._add_group([('Nonexistent Item', 1, False)])

        items = self._items_by_name(self._get_groups())
        self.assertIsNone(items['Nonexistent Item']['acquired'])

    def test_mixed_group_and_plain_items(self):
        self._add_counts({101: 1, 102: 1, 104: 1})
        self._add_group([('Essences', 3, True), ('Wooden Sword', 1, False)])

        items = self._items_by_name(self._get_groups())
        self.assertEqual(items['Essences']['acquired'], 2)
        self.assertEqual(items['Wooden Sword']['acquired'], 1)

    # ------------------------------------------------------------------
    # Isolation and degradation
    # ------------------------------------------------------------------

    def test_counts_from_another_slot_are_not_included(self):
        self._add_counts({101: 1})
        session = Session()
        try:
            session.add(SlotItemCount(room_id=ROOM_UUID, slot_id=99, item_id=102, count=5))
            session.commit()
        finally:
            Session.remove()
        self._add_group([('Essences', 4, True)])

        items = self._items_by_name(self._get_groups())
        self.assertEqual(items['Essences']['acquired'], 1)

    def test_missing_datapackage_degrades_to_null(self):
        """No checksum for the slot's game: progress is omitted, definitions still return."""
        session = Session()
        try:
            room = session.query(TrackedRoom).filter_by(id=self.room_db_id).first()
            room.game_checksums_json = json.dumps({})
            session.commit()
        finally:
            Session.remove()
        self._add_counts({101: 3})
        self._add_group([('Essences', 3, True), ('Wooden Sword', 1, False)])

        payload = self._get_groups()
        items = self._items_by_name(payload)
        self.assertEqual(len(payload), 1)
        self.assertIsNone(items['Essences']['acquired'])
        self.assertIsNone(items['Wooden Sword']['acquired'])

    def test_triggered_group_still_reports_progress(self):
        self._add_counts({101: 1, 102: 1, 103: 1})
        self._add_group([('Essences', 3, True)], is_triggered=True)

        payload = self._get_groups()
        self.assertTrue(payload[0]['is_triggered'])
        self.assertEqual(self._items_by_name(payload)['Essences']['acquired'], 3)


if __name__ == '__main__':
    unittest.main()
