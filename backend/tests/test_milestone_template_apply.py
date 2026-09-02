import os
import sys
import unittest
import json

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_template_apply.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import (
    Base, User, TrackedRoom, UserRoomSubscription, UserTrackedSlot,
    ThresholdGroup, ThresholdGroupItem, MilestoneTemplate, MilestoneTemplateItem,
    DatapackageCache,
)
from app.services import milestone_template_service
from app.utils import TRACK_MODE_PLAY, TRACK_MODE_WATCH

ROOM_UUID = 'room-uuid-template-apply'
CHECKSUM = 'chk_mm2'
GAME = 'Mega Man 2'
SLOT_ID = 4

# The seed's real item list. Anything a template names outside this does not exist here.
SEED_ITEMS = ['Bubble Lead', 'Metal Blade', 'Quick Boomerang', 'Item 1']
SEED_ITEM_GROUPS = {'Weapons': ['Bubble Lead', 'Metal Blade'], 'Items': ['Item 1']}


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


class TemplateApplyTestBase(unittest.TestCase):
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
                cached_players_json=json.dumps([
                    {'slot_id': SLOT_ID, 'name': 'Rock', 'game': GAME},
                    {'slot_id': SLOT_ID + 1, 'name': 'Roll', 'game': GAME},
                ]),
            )
            session.add(room)
            session.flush()
            self.room_db_id = room.id

            session.add_all([
                UserRoomSubscription(user_id=user.id, room_id=room.id, alias='Room'),
                UserRoomSubscription(user_id=other.id, room_id=room.id, alias='Room'),
            ])

            slot = UserTrackedSlot(
                user_id=user.id, room_id=room.id, slot_id=SLOT_ID, track_mode=TRACK_MODE_PLAY
            )
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
        engine.dispose()
        _remove_test_db()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        _remove_test_db()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _auth(self, token=None):
        return {'Authorization': f'Bearer {token or self.token}'}

    def _cache_datapackage(self, items=SEED_ITEMS, groups=SEED_ITEM_GROUPS, checksum=CHECKSUM):
        session = Session()
        try:
            for i, name in enumerate(items):
                session.add(DatapackageCache(
                    game=GAME, checksum=checksum, entity_type='item',
                    entity_id=1000 + i, entity_name=name,
                ))
            if groups is not None:
                session.add(DatapackageCache(
                    game=GAME, checksum=checksum, entity_type='item_name_groups_json',
                    entity_id=1, entity_name=json.dumps(groups),
                ))
            session.commit()
        finally:
            Session.remove()

    def _make_template(self, name, items, auto_apply=False, game=GAME, user_id=None):
        session = Session()
        try:
            template = MilestoneTemplate(
                user_id=user_id or self.user_id,
                game_name=game,
                name=name,
                auto_apply=auto_apply,
            )
            session.add(template)
            session.flush()
            for item_name, quantity, is_group in items:
                session.add(MilestoneTemplateItem(
                    template_id=template.id, item_name=item_name,
                    quantity=quantity, is_group=is_group,
                ))
            session.commit()
            return template.id
        finally:
            Session.remove()

    def _groups(self, tracked_slot_id=None):
        """Re-reads groups through a fresh session so a lost commit cannot hide."""
        session = Session()
        try:
            groups = session.query(ThresholdGroup).filter_by(
                user_tracked_slot_id=tracked_slot_id or self.tracked_slot_id
            ).all()
            return [
                (g.name, sorted((i.item_name, i.quantity, i.is_group) for i in g.items))
                for g in groups
            ]
        finally:
            Session.remove()

    def _bulk(self, groups, token=None, slot_id=SLOT_ID):
        return self.client.post(
            f'/rooms/{self.room_db_id}/slots/{slot_id}/threshold-groups/bulk',
            json={'groups': groups},
            headers=self._auth(token),
        )


class TestBulkThresholdGroupCreate(TemplateApplyTestBase):
    """
    POST .../threshold-groups/bulk -- what the app's "Apply Templates" sheet calls when the
    user ticks several templates at once. Ticking three has to mean three groups or none.
    """

    def test_creates_every_group_in_one_call(self):
        resp = self._bulk([
            {'name': 'Weapons', 'items': [{'item_name': 'Metal Blade', 'quantity': 1}]},
            {'name': 'Mobility', 'items': [
                {'item_name': 'Item 1', 'quantity': 1},
                {'item_name': 'Bubble Lead', 'quantity': 2},
            ]},
        ])
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertEqual(len(body['created']), 2)
        self.assertEqual(body['skipped'], [])

        stored = dict(self._groups())
        self.assertEqual(sorted(stored.keys()), ['Mobility', 'Weapons'])
        self.assertEqual(stored['Mobility'], [('Bubble Lead', 2, False), ('Item 1', 1, False)])

    def test_skips_a_name_the_slot_already_uses(self):
        self._bulk([{'name': 'Weapons', 'items': [{'item_name': 'Metal Blade', 'quantity': 1}]}])

        resp = self._bulk([
            {'name': 'Weapons', 'items': [{'item_name': 'Bubble Lead', 'quantity': 1}]},
            {'name': 'Mobility', 'items': [{'item_name': 'Item 1', 'quantity': 1}]},
        ])
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertEqual([g['name'] for g in body['created']], ['Mobility'])
        self.assertEqual(body['skipped'], [{'name': 'Weapons', 'reason': 'duplicate_name'}])

        # The original group keeps its items -- a duplicate is skipped, never merged.
        self.assertEqual(dict(self._groups())['Weapons'], [('Metal Blade', 1, False)])

    def test_suppresses_duplicates_inside_one_request(self):
        resp = self._bulk([
            {'name': 'Weapons', 'items': [{'item_name': 'Metal Blade', 'quantity': 1}]},
            {'name': 'weapons', 'items': [{'item_name': 'Bubble Lead', 'quantity': 1}]},
        ])
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(resp.get_json()['created']), 1)
        self.assertEqual(len(self._groups()), 1)

    def test_reports_a_group_with_no_usable_items_instead_of_failing_the_batch(self):
        resp = self._bulk([
            {'name': 'Empty', 'items': []},
            {'name': 'Bad Qty', 'items': [{'item_name': 'Metal Blade', 'quantity': 0}]},
            {'name': 'Good', 'items': [{'item_name': 'Metal Blade', 'quantity': 1}]},
        ])
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertEqual([g['name'] for g in body['created']], ['Good'])
        self.assertEqual(
            sorted(s['name'] for s in body['skipped']), ['Bad Qty', 'Empty']
        )

    def test_creates_nothing_when_no_group_is_usable(self):
        resp = self._bulk([{'name': 'Empty', 'items': []}])
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._groups(), [])

    def test_rejects_an_empty_request(self):
        resp = self.client.post(
            f'/rooms/{self.room_db_id}/slots/{SLOT_ID}/threshold-groups/bulk',
            json={'groups': []},
            headers=self._auth(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_rejects_another_users_slot(self):
        resp = self._bulk(
            [{'name': 'Weapons', 'items': [{'item_name': 'Metal Blade', 'quantity': 1}]}],
            token=self.other_token,
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self._groups(), [])

    def test_refuses_to_push_a_slot_past_the_group_cap(self):
        cap = milestone_template_service.MAX_GROUPS_PER_SLOT
        resp = self._bulk([
            {'name': f'G{i}', 'items': [{'item_name': 'Metal Blade', 'quantity': 1}]}
            for i in range(cap + 1)
        ])
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._groups(), [])


class TestTemplateAutoApplyFlag(TemplateApplyTestBase):
    """The per-template "always add to new slots I play" switch."""

    def test_flag_round_trips_through_the_templates_list(self):
        template_id = self._make_template('Standard', [('Metal Blade', 1, False)])

        resp = self.client.get('/milestone-templates', headers=self._auth())
        self.assertFalse(resp.get_json()[0]['auto_apply'])

        resp = self.client.put(
            f'/milestone-templates/{template_id}/auto-apply',
            json={'auto_apply': True},
            headers=self._auth(),
        )
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get('/milestone-templates', headers=self._auth())
        self.assertTrue(resp.get_json()[0]['auto_apply'])

    def test_toggle_requires_the_field(self):
        template_id = self._make_template('Standard', [('Metal Blade', 1, False)])
        resp = self.client.put(
            f'/milestone-templates/{template_id}/auto-apply', json={}, headers=self._auth()
        )
        self.assertEqual(resp.status_code, 400)

    def test_toggle_rejects_another_users_template(self):
        template_id = self._make_template('Standard', [('Metal Blade', 1, False)])
        resp = self.client.put(
            f'/milestone-templates/{template_id}/auto-apply',
            json={'auto_apply': True},
            headers=self._auth(self.other_token),
        )
        self.assertEqual(resp.status_code, 404)

    def test_editing_a_template_without_the_field_leaves_the_switch_alone(self):
        template_id = self._make_template('Standard', [('Metal Blade', 1, False)], auto_apply=True)
        resp = self.client.put(
            f'/milestone-templates/{template_id}',
            json={
                'name': 'Standard',
                'game_name': GAME,
                'items': [{'item_name': 'Bubble Lead', 'quantity': 1}],
            },
            headers=self._auth(),
        )
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get('/milestone-templates', headers=self._auth())
        self.assertTrue(resp.get_json()[0]['auto_apply'])


class TestAutoApplyPendingFlagging(TemplateApplyTestBase):
    """
    Which slots become auto-apply candidates. Auto-apply is forward-only: nothing already in a
    user's library is ever back-filled, so the flag is only ever set by a live tracking action.
    """

    def _put_slots(self, tracked_ids, modes=None):
        payload = {'tracked_slot_ids': tracked_ids}
        if modes:
            payload['slot_modes'] = modes
        return self.client.put(
            f'/rooms/{self.room_db_id}/slots', json=payload, headers=self._auth()
        )

    def _pending(self, slot_id):
        session = Session()
        try:
            slot = session.query(UserTrackedSlot).filter_by(
                user_id=self.user_id, room_id=self.room_db_id, slot_id=slot_id
            ).first()
            return None if slot is None else slot.auto_apply_pending
        finally:
            Session.remove()

    def test_a_newly_played_slot_is_flagged(self):
        resp = self._put_slots([SLOT_ID, SLOT_ID + 1], {str(SLOT_ID + 1): TRACK_MODE_PLAY})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self._pending(SLOT_ID + 1))

    def test_a_watch_only_slot_is_not_flagged(self):
        resp = self._put_slots([SLOT_ID, SLOT_ID + 1], {str(SLOT_ID + 1): TRACK_MODE_WATCH})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(self._pending(SLOT_ID + 1))

    def test_flipping_watch_to_play_flags_the_slot(self):
        self._put_slots([SLOT_ID, SLOT_ID + 1], {str(SLOT_ID + 1): TRACK_MODE_WATCH})
        self.assertFalse(self._pending(SLOT_ID + 1))

        self._put_slots([SLOT_ID, SLOT_ID + 1], {str(SLOT_ID + 1): TRACK_MODE_PLAY})
        self.assertTrue(self._pending(SLOT_ID + 1))

    def test_a_slot_already_in_the_library_is_untouched(self):
        # The fixture slot predates the feature: it must stay unflagged so turning auto-apply
        # on never reaches backwards into slots the user is already playing.
        self.assertFalse(self._pending(SLOT_ID))


class TestAutoApplyPass(TemplateApplyTestBase):
    """
    The poller pass that turns auto_apply templates into real milestone groups.

    Everything here goes through apply_pending_for_room with the same arguments the poller
    hands it -- the parsed player list and game checksum map from the room cache.
    """

    def _slot(self, session, slot_id=SLOT_ID):
        return session.query(UserTrackedSlot).filter_by(
            user_id=self.user_id, room_id=self.room_db_id, slot_id=slot_id
        ).first()

    def _run_pass(self, players=None, checksums=None):
        """Runs the pass and commits, mirroring the poller's own transaction."""
        session = Session()
        try:
            slots = session.query(UserTrackedSlot).filter_by(room_id=self.room_db_id).all()
            handled = milestone_template_service.apply_pending_for_room(
                session,
                players if players is not None else [
                    {'slot_id': SLOT_ID, 'name': 'Rock', 'game': GAME}
                ],
                checksums if checksums is not None else {GAME: CHECKSUM},
                slots,
            )
            session.commit()
            return handled
        finally:
            Session.remove()

    def _mark_pending(self, slot_id=SLOT_ID):
        session = Session()
        try:
            self._slot(session, slot_id).auto_apply_pending = True
            session.commit()
        finally:
            Session.remove()

    def _pending(self, slot_id=SLOT_ID):
        session = Session()
        try:
            return self._slot(session, slot_id).auto_apply_pending
        finally:
            Session.remove()

    def test_applies_every_auto_template_for_the_game(self):
        self._cache_datapackage()
        self._make_template('Weapons', [('Metal Blade', 1, False)], auto_apply=True)
        self._make_template('Mobility', [('Item 1', 1, False)], auto_apply=True)
        self._mark_pending()

        self.assertEqual(self._run_pass(), 1)
        self.assertEqual(sorted(name for name, _ in self._groups()), ['Mobility', 'Weapons'])
        self.assertFalse(self._pending())

    def test_ignores_templates_the_user_did_not_switch_on(self):
        self._cache_datapackage()
        self._make_template('Manual Only', [('Metal Blade', 1, False)], auto_apply=False)
        self._mark_pending()

        self._run_pass()
        self.assertEqual(self._groups(), [])
        self.assertFalse(self._pending())

    def test_ignores_templates_for_a_different_game(self):
        self._cache_datapackage()
        self._make_template('Other Game', [('Metal Blade', 1, False)], auto_apply=True, game='Zelda')
        self._mark_pending()

        self._run_pass()
        self.assertEqual(self._groups(), [])

    def test_ignores_another_users_templates(self):
        self._cache_datapackage()
        self._make_template(
            'Theirs', [('Metal Blade', 1, False)], auto_apply=True, user_id=self.other_user_id
        )
        self._mark_pending()

        self._run_pass()
        self.assertEqual(self._groups(), [])

    def test_drops_items_this_seed_does_not_have(self):
        self._cache_datapackage()
        self._make_template(
            'Mixed',
            [('Metal Blade', 1, False), ('Rush Coil', 1, False)],
            auto_apply=True,
        )
        self._mark_pending()

        self._run_pass()
        self.assertEqual(dict(self._groups())['Mixed'], [('Metal Blade', 1, False)])

    def test_skips_a_template_no_item_of_which_exists_here(self):
        # A group whose requirements can never be met would pin the milestone open forever,
        # which is worse than not having it at all.
        self._cache_datapackage()
        self._make_template('Stale', [('Rush Coil', 1, False)], auto_apply=True)
        self._mark_pending()

        self._run_pass()
        self.assertEqual(self._groups(), [])
        self.assertFalse(self._pending())

    def test_restores_the_datapackage_casing(self):
        self._cache_datapackage()
        self._make_template('Cased', [('metal BLADE', 2, False)], auto_apply=True)
        self._mark_pending()

        self._run_pass()
        self.assertEqual(dict(self._groups())['Cased'], [('Metal Blade', 2, False)])

    def test_resolves_item_groups_against_the_name_group_list(self):
        self._cache_datapackage()
        self._make_template('Grouped', [('weapons', 3, True)], auto_apply=True)
        self._mark_pending()

        self._run_pass()
        self.assertEqual(dict(self._groups())['Grouped'], [('Weapons', 3, True)])

    def test_an_unknown_item_group_is_dropped(self):
        self._cache_datapackage()
        self._make_template(
            'Grouped', [('Weapons', 3, True), ('Robot Masters', 8, True)], auto_apply=True
        )
        self._mark_pending()

        self._run_pass()
        self.assertEqual(dict(self._groups())['Grouped'], [('Weapons', 3, True)])

    def test_waits_for_the_datapackage_instead_of_applying_unverified_items(self):
        # A brand new room is polled before its datapackage is cached. Applying now would mean
        # writing requirements nothing has checked, so the slot stays pending for a later poll.
        self._make_template('Weapons', [('Metal Blade', 1, False)], auto_apply=True)
        self._mark_pending()

        self.assertEqual(self._run_pass(), 0)
        self.assertEqual(self._groups(), [])
        self.assertTrue(self._pending())

        self._cache_datapackage()
        self.assertEqual(self._run_pass(), 1)
        self.assertEqual([name for name, _ in self._groups()], ['Weapons'])
        self.assertFalse(self._pending())

    def test_waits_when_the_slots_game_is_not_known_yet(self):
        self._cache_datapackage()
        self._make_template('Weapons', [('Metal Blade', 1, False)], auto_apply=True)
        self._mark_pending()

        self.assertEqual(self._run_pass(players=[]), 0)
        self.assertTrue(self._pending())

    def test_does_not_touch_a_slot_that_is_not_pending(self):
        self._cache_datapackage()
        self._make_template('Weapons', [('Metal Blade', 1, False)], auto_apply=True)

        self.assertEqual(self._run_pass(), 0)
        self.assertEqual(self._groups(), [])

    def test_does_not_duplicate_a_group_the_slot_already_has(self):
        self._cache_datapackage()
        self._make_template('Weapons', [('Metal Blade', 1, False)], auto_apply=True)
        self._bulk([{'name': 'Weapons', 'items': [{'item_name': 'Bubble Lead', 'quantity': 1}]}])
        self._mark_pending()

        self._run_pass()
        groups = self._groups()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][1], [('Bubble Lead', 1, False)])

    def test_a_second_pass_is_a_no_op(self):
        self._cache_datapackage()
        self._make_template('Weapons', [('Metal Blade', 1, False)], auto_apply=True)
        self._mark_pending()

        self._run_pass()
        self._run_pass()
        self.assertEqual(len(self._groups()), 1)

    def test_matches_the_game_name_case_insensitively(self):
        self._cache_datapackage()
        self._make_template('Weapons', [('Metal Blade', 1, False)], auto_apply=True, game='mega man 2')
        self._mark_pending()

        self._run_pass()
        self.assertEqual([name for name, _ in self._groups()], ['Weapons'])

    def test_a_failure_never_costs_the_room_its_poll(self):
        self._cache_datapackage()
        self._make_template('Weapons', [('Metal Blade', 1, False)], auto_apply=True)
        self._mark_pending()

        # A malformed player cache is data the poller reads, not something it validates.
        session = Session()
        try:
            slots = session.query(UserTrackedSlot).filter_by(room_id=self.room_db_id).all()
            handled = milestone_template_service.apply_pending_for_room(
                session, ['not-a-dict', None], {GAME: CHECKSUM}, slots
            )
            self.assertEqual(handled, 0)
        finally:
            Session.remove()
        self.assertTrue(self._pending())


if __name__ == '__main__':
    unittest.main()
