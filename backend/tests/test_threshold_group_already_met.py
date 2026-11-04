"""A milestone group made or edited by hand is marked met when the slot is already past it (#521).

`mark_already_satisfied` has always run on the bulk endpoint and on template auto-apply, for
the reason its own docstring gives: a group is evaluated against the slot's *cumulative* item
counts, so one created on a slot that already meets it does not stay quietly satisfied -- it
fires a "milestone reached" push the moment the next unrelated item lands, for something the
user finished hours ago.

The single `POST` and the `PUT` were the two paths that skipped it, which are the two paths a
user drives by hand: making a milestone for items they already hold, or editing one down to
quantities they have already reached. `is_triggered` is what the poller reads to decide whether
a group still has something to announce, so marking it here is what stops the stale push.

The slot holds 3 Fire Essence and 1 Wooden Sword, and nothing else.
"""
import json
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_threshold_already_met.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import (
    Base, DatapackageCache, SlotItemCount, ThresholdGroup, ThresholdGroupItem, TrackedRoom,
    User, UserRoomSubscription, UserTrackedSlot,
)

ROOM_UUID = 'room-uuid-already-met'
CHECKSUM = 'chk_zelda'
GAME = 'Zelda'
SLOT_ID = 3

ITEMS = {101: 'Fire Essence', 102: 'Water Essence', 103: 'Earth Essence', 104: 'Wooden Sword'}
ITEM_GROUPS = {'Essences': ['Fire Essence', 'Water Essence', 'Earth Essence']}
COUNTS = {'Fire Essence': 3, 'Wooden Sword': 1}


def _make_token(app, user_id):
    import jwt as pyjwt
    payload = {
        'user_id': user_id,
        'jti': str(uuid.uuid4()),
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')


class TestThresholdGroupAlreadyMet(unittest.TestCase):
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
                cached_players_json=json.dumps([{'slot_id': SLOT_ID, 'name': 'Link', 'game': GAME}]),
            )
            session.add(room)
            session.flush()
            self.room_db_id = room.id

            # A tracked slot has a composite foreign key to its subscription.
            session.add(UserRoomSubscription(user_id=user.id, room_id=room.id, alias='Test Room'))
            session.flush()
            slot = UserTrackedSlot(user_id=user.id, room_id=room.id, slot_id=SLOT_ID)
            session.add(slot)
            session.flush()
            self.tracked_slot_id = slot.id

            for item_id, name in ITEMS.items():
                session.add(DatapackageCache(
                    game=GAME, checksum=CHECKSUM, entity_type='item',
                    entity_id=item_id, entity_name=name,
                ))
            session.add(DatapackageCache(
                game=GAME, checksum=CHECKSUM, entity_type='item_name_groups_json',
                entity_id=0, entity_name=json.dumps(ITEM_GROUPS),
            ))

            # Seeded the way the poller does, so "already past this milestone" is a real
            # state rather than an assumption. SlotItemCount is keyed by the room's
            # Archipelago uuid, not its database id.
            ids_by_name = {name.lower(): item_id for item_id, name in ITEMS.items()}
            for name, count in COUNTS.items():
                session.add(SlotItemCount(
                    room_id=ROOM_UUID, slot_id=SLOT_ID,
                    item_id=ids_by_name[name.lower()], count=count,
                ))

            session.commit()
            self.token = _make_token(self.app, self.user_id)
        finally:
            Session.remove()

    def tearDown(self):
        Session.remove()
        engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = f"{TEST_DB_PATH}{suffix}"
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _auth(self):
        return {'Authorization': f'Bearer {self.token}'}

    def _url(self, group_id=None):
        base = f'/rooms/{self.room_db_id}/slots/{SLOT_ID}/threshold-groups'
        return base if group_id is None else f'{base}/{group_id}'

    def _post(self, items, name='Milestone'):
        return self.client.post(
            self._url(),
            json={'name': name, 'items': [
                {'item_name': n, 'quantity': q, 'is_group': g} for n, q, g in items
            ]},
            headers=self._auth(),
        )

    def _put(self, group_id, items, name='Milestone'):
        return self.client.put(
            self._url(group_id),
            json={'name': name, 'items': [
                {'item_name': n, 'quantity': q, 'is_group': g} for n, q, g in items
            ]},
            headers=self._auth(),
        )

    def _seed_group(self, items, name='Existing'):
        """An untriggered group written straight to the database, to edit."""
        session = Session()
        try:
            group = ThresholdGroup(
                user_tracked_slot_id=self.tracked_slot_id, name=name, is_triggered=False
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

    def _fetch(self, group_id):
        """Re-read over HTTP, so nothing can hide in a warm identity map."""
        response = self.client.get(self._url(), headers=self._auth())
        self.assertEqual(response.status_code, 200)
        for group in response.get_json():
            if group['id'] == group_id:
                return group
        self.fail(f'group {group_id} is missing from the list')

    # ------------------------------------------------------------------
    # Creating
    # ------------------------------------------------------------------

    def test_a_group_the_slot_already_meets_is_created_met(self):
        response = self._post([('Fire Essence', 2, False)])
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        body = response.get_json()
        # The stored flag first: it is what the poller reads, and asserting the
        # response field before it would fail on a missing key rather than on the
        # behaviour this is here for.
        group = self._fetch(body['id'])
        self.assertTrue(
            group['is_triggered'],
            "left untriggered it fires a stale 'milestone reached' push on the next item"
        )
        self.assertTrue(body['is_triggered'])
        # The items still have to be saved: they go in through the relationship now, so
        # that the already-met check can read them before the commit.
        self.assertEqual(
            [(i['item_name'], i['quantity'], i['is_group'], i['acquired']) for i in group['items']],
            [('Fire Essence', 2, False, 3)]
        )

    def test_a_group_still_ahead_of_the_slot_stays_open(self):
        response = self._post([('Fire Essence', 5, False)])
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.get_json()['is_triggered'])
        self.assertFalse(self._fetch(response.get_json()['id'])['is_triggered'])

    def test_a_group_met_only_in_part_stays_open(self):
        # Every item in a group has to be met for the group to be met.
        response = self._post([('Fire Essence', 2, False), ('Wooden Sword', 2, False)])
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.get_json()['is_triggered'])

    def test_an_item_this_seed_does_not_have_is_not_called_met(self):
        # The single create does not check names against the datapackage, so a
        # requirement nothing resolves is unknowable, not satisfied.
        response = self._post([('Hookshot', 1, False)])
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.get_json()['is_triggered'])

    def test_an_item_group_requirement_is_measured_too(self):
        # 'Essences' expands to three items; the slot holds 3 of one of them.
        met = self._post([('Essences', 3, True)], name='Essences met')
        self.assertTrue(met.get_json()['is_triggered'])
        ahead = self._post([('Essences', 4, True)], name='Essences ahead')
        self.assertFalse(ahead.get_json()['is_triggered'])

    def test_a_slot_with_no_counts_yet_creates_an_open_group(self):
        session = Session()
        try:
            session.query(SlotItemCount).delete()
            session.commit()
        finally:
            Session.remove()
        response = self._post([('Fire Essence', 1, False)])
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.get_json()['is_triggered'])

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------

    def test_an_edit_down_to_quantities_already_reached_is_marked_met(self):
        group_id = self._seed_group([('Fire Essence', 9, False)])
        response = self._put(group_id, [('Fire Essence', 2, False)])
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertTrue(self._fetch(group_id)['is_triggered'])
        self.assertTrue(response.get_json()['is_triggered'])

    def test_an_edit_that_is_still_ahead_stays_open(self):
        group_id = self._seed_group([('Fire Essence', 9, False)])
        response = self._put(group_id, [('Fire Essence', 4, False)])
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()['is_triggered'])
        group = self._fetch(group_id)
        self.assertFalse(group['is_triggered'])
        self.assertEqual([(i['item_name'], i['quantity']) for i in group['items']],
                         [('Fire Essence', 4)])

    def test_an_edit_adding_an_unmet_item_stays_open(self):
        group_id = self._seed_group([('Fire Essence', 9, False)])
        response = self._put(group_id, [('Fire Essence', 2, False), ('Water Essence', 1, False)])
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()['is_triggered'])

    def test_a_group_already_met_still_cannot_be_edited(self):
        # Unchanged: the 400 guard runs before any of this.
        group_id = self._seed_group([('Fire Essence', 1, False)])
        session = Session()
        try:
            session.query(ThresholdGroup).filter_by(id=group_id).first().is_triggered = True
            session.commit()
        finally:
            Session.remove()
        self.assertEqual(self._put(group_id, [('Fire Essence', 2, False)]).status_code, 400)


if __name__ == '__main__':
    unittest.main()
