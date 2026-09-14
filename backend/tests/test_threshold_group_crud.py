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
    Base, User, TrackedRoom, UserRoomSubscription, UserTrackedSlot, ThresholdGroup,
    ThresholdGroupItem
)
from app.services.milestone_template_service import MAX_GROUPS_PER_SLOT

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

            # A tracked slot has a composite foreign key to its subscription, so the
            # subscription has to exist first. Postgres has always required this.
            session.add(UserRoomSubscription(
                user_id=user.id, room_id=room.id, alias='Test Room'
            ))
            session.flush()

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




class TestThresholdGroupCreateCap(unittest.TestCase):
    """
    Covers the per-slot cap on POST .../threshold-groups, the "Create Milestone Group" sheet.

    The bulk endpoint and auto-apply both stop at MAX_GROUPS_PER_SLOT because every untriggered
    group is re-evaluated on every poll. The single create was the one path without it (#322).
    The cap blocks growth only: a slot already over it keeps every group, can still edit and
    delete them, and can add again once it is back under.
    """

    # Same slot fixture as the update tests, without inheriting their tests.
    setUp = TestThresholdGroupUpdate.setUp
    _auth = TestThresholdGroupUpdate._auth
    _put = TestThresholdGroupUpdate._put

    def tearDown(self):
        Session.remove()
        # Before unlinking, so the pool cannot go on serving an unlinked inode on Linux.
        engine.dispose()
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def _fill(self, count, tracked_slot_id=None):
        """Add `count` groups to a slot in one transaction. Returns their ids."""
        session = Session()
        try:
            ids = []
            for i in range(count):
                group = ThresholdGroup(
                    user_tracked_slot_id=tracked_slot_id or self.tracked_slot_id,
                    name=f'Existing {i}', is_triggered=False,
                )
                session.add(group)
                session.flush()
                session.add(ThresholdGroupItem(
                    group_id=group.id, item_name='Bow', quantity=1, is_group=False
                ))
                ids.append(group.id)
            session.commit()
            return ids
        finally:
            Session.remove()

    def _count(self, tracked_slot_id=None):
        session = Session()
        try:
            return session.query(ThresholdGroup).filter_by(
                user_tracked_slot_id=tracked_slot_id or self.tracked_slot_id
            ).count()
        finally:
            Session.remove()

    def _create(self, slot_id=SLOT_ID, name='New One'):
        return self.client.post(
            f'/rooms/{self.room_db_id}/slots/{slot_id}/threshold-groups',
            json={'name': name, 'items': [{'item_name': 'Hookshot', 'quantity': 1}]},
            headers=self._auth(),
        )

    def _delete(self, group_id):
        return self.client.delete(
            f'/rooms/{self.room_db_id}/slots/{SLOT_ID}/threshold-groups/{group_id}',
            headers=self._auth(),
        )

    def test_create_is_refused_at_the_cap_and_writes_nothing(self):
        self._fill(MAX_GROUPS_PER_SLOT)

        r = self._create()

        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json().get('reason'), 'slot_group_limit')
        self.assertEqual(self._count(), MAX_GROUPS_PER_SLOT)

    def test_the_last_group_under_the_cap_is_still_created(self):
        """Exactly at the boundary: a slot one short of the cap may take one more."""
        self._fill(MAX_GROUPS_PER_SLOT - 1)

        r = self._create()

        self.assertEqual(r.status_code, 201)
        self.assertEqual(self._count(), MAX_GROUPS_PER_SLOT)

    def test_a_slot_already_over_the_cap_is_grandfathered_not_trimmed(self):
        """
        Blocking growth, not validating the whole set. A slot that got past the cap through
        the old uncapped path keeps every group, can still edit and delete them, and can add
        again once deletions bring it back under.
        """
        ids = self._fill(MAX_GROUPS_PER_SLOT + 5)

        self.assertEqual(self._create().status_code, 400)
        self.assertEqual(self._count(), MAX_GROUPS_PER_SLOT + 5, "existing groups were touched")

        edit = self._put(ids[0], {'name': 'Renamed', 'items': [{'item_name': 'Bow', 'quantity': 2}]})
        self.assertEqual(edit.status_code, 200, "an over-cap slot could not edit its groups")

        for group_id in ids[-6:]:
            self.assertIn(self._delete(group_id).status_code, (200, 204))
        self.assertEqual(self._count(), MAX_GROUPS_PER_SLOT - 1)

        self.assertEqual(self._create().status_code, 201,
                         "still refused after deleting back under the cap")

    def test_the_cap_is_per_slot(self):
        session = Session()
        try:
            other_slot = UserTrackedSlot(
                user_id=self.user_id, room_id=self.room_db_id, slot_id=SLOT_ID + 1
            )
            session.add(other_slot)
            session.commit()
            other_tracked_slot_id = other_slot.id
        finally:
            Session.remove()
        self._fill(MAX_GROUPS_PER_SLOT)

        r = self._create(slot_id=SLOT_ID + 1)

        self.assertEqual(r.status_code, 201, "a full slot blocked a different slot")
        self.assertEqual(self._count(other_tracked_slot_id), 1)



if __name__ == '__main__':
    unittest.main()
