import os
import sys
import unittest
import json

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_threshold_crud.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import (
    Base, User, TrackedRoom, UserTrackedSlot, ThresholdGroup, ThresholdGroupItem
)

ROOM_UUID = 'room-uuid-crud'
CHECKSUM = 'chk_zelda'
GAME = 'Zelda'
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


class TestThresholdGroupUpdate(unittest.TestCase):
    """
    Covers PUT .../threshold-groups/<id>, the endpoint behind the app's "Edit Milestone Group"
    sheet.

    The route previously returned 200 without ever committing: token_required calls
    Session.remove() before the route body runs, so the session handle_db_errors holds is not
    the session the route mutates, and its implicit commit was a no-op. The edits were rolled
    back on teardown while the client was told the save had succeeded. Every assertion here
    re-reads through a fresh request so a lost commit cannot hide behind a warm identity map.
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

            session.commit()
            self.token = _make_token(self.app, self.user_id)
            self.other_token = _make_token(self.app, self.other_user_id)
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

    def _auth(self, token=None):
        return {'Authorization': f'Bearer {token or self.token}'}

    def _add_group(self, items, name='Milestone', is_triggered=False):
        """items: list of (item_name, quantity, is_group). Returns the new group id."""
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
            return group.id
        finally:
            Session.remove()

    def _put(self, group_id, payload, token=None):
        return self.client.put(
            f'/rooms/{self.room_db_id}/slots/{SLOT_ID}/threshold-groups/{group_id}',
            json=payload,
            headers=self._auth(token),
        )

    def _fetch_group(self, group_id):
        """Re-read the group over HTTP, the way the app does after a save."""
        r = self.client.get(
            f'/rooms/{self.room_db_id}/slots/{SLOT_ID}/threshold-groups',
            headers=self._auth(),
        )
        self.assertEqual(r.status_code, 200)
        for group in r.get_json():
            if group['id'] == group_id:
                return group
        self.fail(f'group {group_id} missing from the threshold-groups listing')

    # ------------------------------------------------------------------
    # The regression: edits must survive the request
    # ------------------------------------------------------------------

    def test_update_persists_name_and_items(self):
        group_id = self._add_group([('Wooden Sword', 1, False)], name='Old Name')

        r = self._put(group_id, {
            'name': 'New Name',
            'items': [
                {'item_name': 'Fire Essence', 'quantity': 2, 'is_group': False},
                {'item_name': 'Essences', 'quantity': 3, 'is_group': True},
            ],
        })
        self.assertEqual(r.status_code, 200)

        group = self._fetch_group(group_id)
        self.assertEqual(group['name'], 'New Name')
        by_name = {i['item_name']: i for i in group['items']}
        self.assertEqual(set(by_name), {'Fire Essence', 'Essences'})
        self.assertEqual(by_name['Fire Essence']['quantity'], 2)
        self.assertFalse(by_name['Fire Essence']['is_group'])
        self.assertEqual(by_name['Essences']['quantity'], 3)
        self.assertTrue(by_name['Essences']['is_group'])

    def test_update_removes_items_dropped_by_the_edit(self):
        group_id = self._add_group([
            ('Wooden Sword', 1, False),
            ('Fire Essence', 1, False),
        ])

        r = self._put(group_id, {
            'name': 'Milestone',
            'items': [{'item_name': 'Wooden Sword', 'quantity': 1, 'is_group': False}],
        })
        self.assertEqual(r.status_code, 200)

        group = self._fetch_group(group_id)
        self.assertEqual([i['item_name'] for i in group['items']], ['Wooden Sword'])

        # The dropped row is gone, not merely detached from the group.
        session = Session()
        try:
            orphans = session.query(ThresholdGroupItem).filter_by(item_name='Fire Essence').count()
            self.assertEqual(orphans, 0)
        finally:
            Session.remove()

    def test_update_keeps_item_removed_and_re_added_in_one_edit(self):
        """The clear()/re-append pair must not collide with its own outgoing rows."""
        group_id = self._add_group([
            ('Wooden Sword', 1, False),
            ('Fire Essence', 1, False),
        ])

        r = self._put(group_id, {
            'name': 'Milestone',
            'items': [{'item_name': 'Wooden Sword', 'quantity': 4, 'is_group': False}],
        })
        self.assertEqual(r.status_code, 200)

        group = self._fetch_group(group_id)
        by_name = {i['item_name']: i for i in group['items']}
        self.assertEqual(set(by_name), {'Wooden Sword'})
        self.assertEqual(by_name['Wooden Sword']['quantity'], 4)

    def test_update_clearing_name_persists_null(self):
        group_id = self._add_group([('Wooden Sword', 1, False)], name='Named')

        r = self._put(group_id, {
            'name': '   ',
            'items': [{'item_name': 'Wooden Sword', 'quantity': 1, 'is_group': False}],
        })
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self._fetch_group(group_id)['name'])

    # ------------------------------------------------------------------
    # Rejections must leave the stored group untouched
    # ------------------------------------------------------------------

    def test_update_with_no_items_rejected(self):
        group_id = self._add_group([('Wooden Sword', 1, False)])

        r = self._put(group_id, {'name': 'New Name', 'items': []})
        self.assertEqual(r.status_code, 400)

        group = self._fetch_group(group_id)
        self.assertEqual(group['name'], 'Milestone')
        self.assertEqual([i['item_name'] for i in group['items']], ['Wooden Sword'])

    def test_update_with_only_invalid_items_rejected(self):
        group_id = self._add_group([('Wooden Sword', 1, False)])

        r = self._put(group_id, {
            'name': 'New Name',
            'items': [{'item_name': '  ', 'quantity': 0, 'is_group': False}],
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(
            [i['item_name'] for i in self._fetch_group(group_id)['items']],
            ['Wooden Sword'],
        )

    def test_update_triggered_group_rejected(self):
        group_id = self._add_group([('Wooden Sword', 1, False)], is_triggered=True)

        r = self._put(group_id, {
            'name': 'New Name',
            'items': [{'item_name': 'Fire Essence', 'quantity': 1, 'is_group': False}],
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(
            [i['item_name'] for i in self._fetch_group(group_id)['items']],
            ['Wooden Sword'],
        )

    def test_update_unknown_group_returns_404(self):
        r = self._put(999999, {
            'items': [{'item_name': 'Fire Essence', 'quantity': 1, 'is_group': False}],
        })
        self.assertEqual(r.status_code, 404)

    def test_update_another_users_group_returns_404(self):
        group_id = self._add_group([('Wooden Sword', 1, False)])

        r = self._put(group_id, {
            'name': 'Hijacked',
            'items': [{'item_name': 'Fire Essence', 'quantity': 1, 'is_group': False}],
        }, token=self.other_token)
        self.assertEqual(r.status_code, 404)

        group = self._fetch_group(group_id)
        self.assertEqual(group['name'], 'Milestone')
        self.assertEqual([i['item_name'] for i in group['items']], ['Wooden Sword'])


if __name__ == '__main__':
    unittest.main()
