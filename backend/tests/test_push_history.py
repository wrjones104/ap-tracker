"""
Tests for the item payload a push carries (#416).

A push used to make every device call back for the items it announced. Now the push carries
them, plus each slot's previous newest id so the app can tell they follow on from what it has.
These run a whole poll through db_process_poll_data, then check the payload against what
/history/sync returns for the same items, field for field.
"""
import asyncio
import json
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import event

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_push_history.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import (
    Base, User, TrackedRoom, UserRoomSubscription, UserTrackedSlot, DatapackageCache,
    NotifiedItem, NotifiedHint, Device, UserIgnoreItem
)
from app.poller import db_process_poll_data, send_push_notifications
from app.services.push_history import (
    FCM_MESSAGE_BUDGET_BYTES, FILTER_IGNORED, fits_in_push, history_push_users
)

ROOM_UUID = 'room-uuid-push-history'
ZELDA, METROID = 'Zelda', 'Metroid'
CHK_ZELDA, CHK_METROID = 'chk_zelda', 'chk_metroid'

ZELDA_ITEMS = {101: 'Rupee', 102: 'Master Sword', 103: 'Heart Container'}
METROID_ITEMS = {201: 'Missile', 202: 'Energy Tank'}
METROID_LOCATIONS = {9001: 'Brinstar Ledge', 9002: 'Norfair Lava', 9003: 'Tourian Gate'}

PLAYERS = [
    {'slot_id': 1, 'name': 'Link', 'game': ZELDA, 'alias': 'Hero', 'total_locations': 10},
    {'slot_id': 2, 'name': 'Samus', 'game': METROID, 'total_locations': 10},
    {'slot_id': 3, 'name': 'Ridley', 'game': METROID, 'total_locations': 10},
]

PROGRESSION, FILLER = 1, 0


def _make_token(app, user_id):
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


class PushHistoryTestCase(unittest.TestCase):
    """A room with slots 1 (Zelda) and 2 (Metroid) tracked, three items already stored for slot 1."""

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
                room_id=ROOM_UUID, tracker_id='tracker-abc', hostname='archipelago.gg', is_setup=True,
                game_checksums_json=json.dumps({ZELDA: CHK_ZELDA, METROID: CHK_METROID}),
                cached_players_json=json.dumps(PLAYERS),
            )
            session.add(room)
            session.flush()
            self.room_db_id = room.id

            session.add(UserRoomSubscription(user_id=user.id, room_id=room.id, alias='Mine', icon_name='sword'))
            session.flush()
            session.add_all([
                UserTrackedSlot(user_id=user.id, room_id=room.id, slot_id=1, needs_backfill=False),
                UserTrackedSlot(user_id=user.id, room_id=room.id, slot_id=2, needs_backfill=False),
            ])
            session.add(Device(user_id=user.id, fcm_token='tok_android', platform='android'))

            for checksum, game, items in [(CHK_ZELDA, ZELDA, ZELDA_ITEMS), (CHK_METROID, METROID, METROID_ITEMS)]:
                for item_id, name in items.items():
                    session.add(DatapackageCache(
                        game=game, checksum=checksum, entity_type='item', entity_id=item_id, entity_name=name))
            for loc_id, name in METROID_LOCATIONS.items():
                session.add(DatapackageCache(
                    game=METROID, checksum=CHK_METROID, entity_type='location', entity_id=loc_id, entity_name=name))

            # Slot 1 already holds indices 0-2; slot 2 has never received anything.
            for index in range(3):
                session.add(NotifiedItem(
                    room_id=ROOM_UUID, receiving_slot_id=1, sending_slot_id=3,
                    item_id=101, location_id=9001, item_index=index, item_flags=FILLER))
            session.commit()
            self.slot1_prior_max = session.query(NotifiedItem.id).order_by(NotifiedItem.id.desc()).first()[0]
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

    def _slot1_items(self, *new):
        """Slot 1's received list: the three stored items, then `new` as (item, loc, sender, flags)."""
        return [[101, 9001, 3, FILLER]] * 3 + [list(entry) for entry in new]

    def _poll(self, slot1_new=(), slot2=(), slot3=(), hints=()):
        session = Session()
        try:
            room = session.query(TrackedRoom).filter_by(id=self.room_db_id).one()
            room_data = {
                'cached_players_json_str': room.cached_players_json,
                'game_checksums_json_str': room.game_checksums_json,
                'is_complete_status': room.is_complete,
            }
        finally:
            Session.remove()
        tracker_data = {
            'aliases': [{'player': 1, 'alias': 'Hero'}],
            'player_items_received': [
                {'player': 1, 'items': self._slot1_items(*slot1_new)},
                {'player': 2, 'items': [list(e) for e in slot2]},
                {'player': 3, 'items': [list(e) for e in slot3]},
            ],
            'hints': [{'hints': [list(h) for h in hints]}],
        }
        return db_process_poll_data(self.room_db_id, ROOM_UUID, tracker_data, room_data) or {}

    def _history(self, payloads, user_id=None):
        raw = payloads[user_id or self.user_id]['history']
        self.assertIsNotNone(raw, "expected the push to carry its items")
        return json.loads(raw)

    def _add_user(self, name, slots):
        """Another subscriber to the room, tracking `slots`, with an Android device."""
        session = Session()
        try:
            user = User(discord_id=name, discord_username=name)
            session.add(user)
            session.flush()
            session.add(UserRoomSubscription(user_id=user.id, room_id=self.room_db_id, alias=name))
            session.flush()
            for slot in slots:
                session.add(UserTrackedSlot(user_id=user.id, room_id=self.room_db_id, slot_id=slot,
                                            needs_backfill=False))
            session.add(Device(user_id=user.id, fcm_token=f'tok_{name}', platform='android'))
            session.commit()
            return user.id
        finally:
            Session.remove()

    def _add_hint(self, updated_at, is_found=False):
        """A hint already stored for the room: Link's Heart Container, at Ridley's Tourian Gate."""
        session = Session()
        try:
            session.add(NotifiedHint(
                room_id=ROOM_UUID, item_owner_id=1, location_owner_id=3, item_id=103, location_id=9003,
                is_found=is_found, item_flags=PROGRESSION, timestamp=updated_at, updated_at=updated_at))
            session.commit()
        finally:
            Session.remove()

    def _sync_response(self, watermarks):
        response = self.client.post(
            '/history/sync',
            json={'items': [
                {'room_db_id': self.room_db_id, 'slot_id': slot, 'last_id': last_id}
                for slot, last_id in watermarks.items()
            ], 'hints': []},
            headers={'Authorization': f'Bearer {self.token}'},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def _sync(self, watermarks):
        return self._sync_response(watermarks)['new_items']

    @staticmethod
    def _as_sync_rows(history):
        """Expand the compact payload into /history/sync's item shape, as the app will."""
        players = history['players']
        rows = []
        for item_id, slot, sender, item_name, loc_name, flags, count, bits, ts in history['items']:
            receiver = players[str(slot)]
            sender_row = players[str(sender)]
            rows.append({
                'id': item_id,
                'playerName': receiver[0],
                'playerAlias': receiver[1],
                'receivingGame': receiver[2],
                'itemName': item_name,
                'senderName': sender_row[0],
                'senderAlias': sender_row[1],
                'senderGame': sender_row[2],
                'locationName': loc_name,
                'isPlayerFinished': receiver[3],
                'playerHasAllChecks': receiver[4],
                'itemFlags': flags,
                'timestamp': ts,
                'room_db_id': history['room'],
                'icon_name': history['icon'],
                'tracker_id': history['tracker'],
                'slot_id': slot,
                'host': history['host'],
                'receivedCount': count,
                'isIgnored': bool(bits & 1),
                'isWhitelisted': bool(bits & 2),
            })
        return rows


class TestPushCarriesItems(PushHistoryTestCase):

    def test_an_item_push_carries_its_items(self):
        payloads = self._poll(slot1_new=[(102, 9002, 3, PROGRESSION)])

        history = self._history(payloads)
        self.assertEqual(history['v'], 1)
        self.assertEqual(history['room'], self.room_db_id)
        self.assertEqual(history['slots'], [[1, self.slot1_prior_max]])
        self.assertEqual(len(history['items']), 1)
        item = history['items'][0]
        self.assertGreater(item[0], self.slot1_prior_max)
        self.assertEqual(item[1:5], [1, 3, 'Master Sword', 'Norfair Lava'])

    def test_payload_matches_history_sync_field_for_field(self):
        payloads = self._poll(
            slot1_new=[(102, 9002, 3, PROGRESSION), (101, 9003, 3, FILLER)],
            slot2=[(202, 9001, 3, PROGRESSION)],
        )

        from_push = self._as_sync_rows(self._history(payloads))
        # room_alias is the one field the app does not store with an item.
        from_sync = [{k: v for k, v in row.items() if k != 'room_alias'}
                     for row in self._sync({1: self.slot1_prior_max, 2: None})]
        self.assertEqual(len(from_sync), 3)

        self.assertEqual(
            sorted(from_push, key=lambda r: r['id']),
            sorted(from_sync, key=lambda r: r['id']),
        )

    def test_unannounced_items_of_tracked_slots_ride_along(self):
        # Filler is not announced by default, but the app stores every item of a tracked slot.
        # Leaving it out would let the app advance past it and never fetch it.
        payloads = self._poll(
            slot1_new=[(102, 9002, 3, PROGRESSION)],
            slot2=[(201, 9001, 3, FILLER)],
        )

        history = self._history(payloads)
        self.assertEqual(history['slots'], [[1, self.slot1_prior_max], [2, None]])
        self.assertEqual(sorted(i[1] for i in history['items']), [1, 2])

    def test_each_user_gets_only_their_own_slots(self):
        # Slot 3 is tracked, by someone else, so its item is stored and reaches the builder.
        other_id = self._add_user('user_b', slots=[3])

        payloads = self._poll(
            slot1_new=[(102, 9002, 3, PROGRESSION)],
            slot3=[(201, 9001, 2, PROGRESSION)],
        )

        mine = self._history(payloads)
        self.assertEqual([s[0] for s in mine['slots']], [1])
        self.assertTrue(all(i[1] == 1 for i in mine['items']))
        theirs = self._history(payloads, other_id)
        self.assertEqual([s[0] for s in theirs['slots']], [3])
        self.assertTrue(all(i[1] == 3 for i in theirs['items']))

    def test_hints_through_matches_the_syncs_hint_cursor(self):
        # The app compares it with the cursor /history/sync gave it, so both must be the same
        # value in the same format.
        self._add_hint(datetime(2026, 10, 20, 9, 30, 15, 123456))

        payloads = self._poll(slot1_new=[(102, 9002, 3, PROGRESSION)])

        history = self._history(payloads)
        cursor = self._sync_response({1: None, 2: None})['hint_watermarks'][str(self.room_db_id)]
        self.assertEqual(history['hints_through'], '2026-10-20T09:30:15.123456Z')
        self.assertEqual(history['hints_through'], cursor)

    def test_hints_through_is_null_for_a_room_without_hints(self):
        payloads = self._poll(slot1_new=[(102, 9002, 3, PROGRESSION)])

        self.assertIsNone(self._history(payloads)['hints_through'])

    def test_ignore_rules_flag_items_as_the_sync_would(self):
        session = Session()
        try:
            session.add(UserIgnoreItem(user_id=self.user_id, item_name='Rupee', game_name=ZELDA))
            session.commit()
        finally:
            Session.remove()

        payloads = self._poll(slot1_new=[(102, 9002, 3, PROGRESSION), (101, 9003, 3, PROGRESSION)])

        bits = {i[3]: i[7] for i in self._history(payloads)['items']}
        self.assertEqual(bits['Rupee'], FILTER_IGNORED)
        self.assertEqual(bits['Master Sword'], 0)


class TestPushWithholdsItems(PushHistoryTestCase):
    """Whenever a sync would bring more than these items, the push leaves the field out."""

    def test_withheld_when_the_rooms_hints_changed(self):
        payloads = self._poll(
            slot1_new=[(102, 9002, 3, PROGRESSION)],
            hints=[(1, 3, 9003, 103, False, '', PROGRESSION)],
        )

        self.assertIn(self.user_id, payloads)
        self.assertIsNone(payloads[self.user_id]['history'])

    def test_withheld_when_a_stored_hint_was_just_found(self):
        # A found hint sends no push of its own, but the phone still needs the change.
        self._add_hint(datetime(2026, 10, 20, 9, 30), is_found=False)

        payloads = self._poll(
            slot1_new=[(102, 9002, 3, PROGRESSION)],
            hints=[(1, 3, 9003, 103, True, '', PROGRESSION)],
        )

        self.assertEqual([n['type'] for n in payloads[self.user_id]['notifications']], ['item_progression'])
        self.assertIsNone(payloads[self.user_id]['history'])

    def test_withheld_when_the_batch_holds_more_than_items(self):
        self.assertEqual(history_push_users({
            1: [{'type': 'item_progression'}, {'type': 'player_finish'}],
            2: [{'type': 'item_useful'}, {'type': 'item_filler'}],
            3: [{'type': 'item_milestone'}],
            4: [{'type': 'hint'}],
            5: [],
        }), {2})

    def test_no_push_no_payload(self):
        # Filler only: nothing is announced, so there is no push to carry anything.
        payloads = self._poll(slot2=[(201, 9001, 3, FILLER)])

        self.assertNotIn(self.user_id, payloads)


class TestPayloadFailuresKeepThePoll(PushHistoryTestCase):
    """
    A database error while building the payload costs the payload, never the poll.

    The failing statement is real SQL the database rejects. SQLite carries on after that anyway,
    so the tests also check that the error was rolled back to a savepoint: that is what keeps
    Postgres, which aborts the whole transaction, from losing the items and the push.
    """

    def _poll_with_broken_query(self, marker, broken):
        statements = []

        def break_it(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
            if marker in statement:
                statement = statement.replace(marker, broken)
            return statement, parameters

        event.listen(engine, 'before_cursor_execute', break_it, retval=True)
        try:
            payloads = self._poll(slot1_new=[(102, 9002, 3, PROGRESSION)])
        finally:
            event.remove(engine, 'before_cursor_execute', break_it)
        return payloads, statements

    def _assert_poll_survived(self, payloads, statements):
        self.assertTrue(any(s.startswith('ROLLBACK TO SAVEPOINT') for s in statements))
        # The push still goes out, without the field, so the app syncs.
        self.assertIsNone(payloads[self.user_id]['history'])
        self.assertEqual([n['type'] for n in payloads[self.user_id]['notifications']], ['item_progression'])
        # And the item is stored.
        session = Session()
        try:
            self.assertEqual(session.query(NotifiedItem).filter_by(receiving_slot_id=1).count(), 4)
        finally:
            Session.remove()

    def test_a_failed_cursor_read(self):
        payloads, statements = self._poll_with_broken_query(
            'max(notified_items.id)', 'max(notified_items.no_such_column)')
        self._assert_poll_survived(payloads, statements)

    def test_a_failed_read_back(self):
        payloads, statements = self._poll_with_broken_query(
            'notified_items.item_index) IN', 'notified_items.no_such_column) IN')
        self._assert_poll_survived(payloads, statements)


class TestCoverageLog(PushHistoryTestCase):
    """
    One [PUSH_PAYLOAD] line per user batch with item pushes, so prod shows what share of item
    pushes would still need a sync before the app that relies on the payload ships (#501).
    """

    def _payload_lines(self, logs):
        return [line for line in logs.output if '[PUSH_PAYLOAD]' in line]

    def test_a_carried_payload_is_logged_with_its_size(self):
        with self.assertLogs(level='INFO') as logs:
            payloads = self._poll(slot1_new=[(102, 9002, 3, PROGRESSION)])

        history = payloads[self.user_id]['history']
        [line] = self._payload_lines(logs)
        self.assertIn(f'room={self.room_db_id} user={self.user_id} carried items=1 '
                      f'bytes={len(history.encode("utf-8"))} messages=1/1 data_only_devices=0/1', line)

    def test_a_withheld_payload_is_logged_with_its_reason(self):
        with self.assertLogs(level='INFO') as logs:
            self._poll(slot1_new=[(102, 9002, 3, PROGRESSION)],
                       hints=[(1, 3, 9003, 103, False, '', PROGRESSION)])

        [line] = self._payload_lines(logs)
        self.assertIn(f'user={self.user_id} withheld reason=hints_changed', line)

    def test_a_payload_that_fits_no_message_is_dropped_as_too_large(self):
        from app.poller import _log_payload_coverage
        bundle = {'title': 'New Items (200)', 'body': '…', 'type': 'item_progression',
                  'bundled_items': json.dumps([f'Progressive Sword #{i}' for i in range(200)])}

        with self.assertLogs(level='INFO') as logs:
            sent = _log_payload_coverage(1, 7, '{"v":1,"items":[]}', [bundle], {'android': ['t']}, set(), None)

        self.assertIsNone(sent)
        self.assertIn('user=7 withheld reason=too_large', self._payload_lines(logs)[0])

    def test_data_only_devices_reach_the_push_and_the_log(self):
        session = Session()
        try:
            session.query(Device).filter_by(fcm_token='tok_android').update({'data_only_push': True})
            session.add(Device(user_id=self.user_id, fcm_token='tok_old_phone', platform='android'))
            session.commit()
        finally:
            Session.remove()

        with self.assertLogs(level='INFO') as logs:
            payloads = self._poll(slot1_new=[(102, 9002, 3, PROGRESSION)])

        self.assertEqual(payloads[self.user_id]['data_only_tokens'], {'tok_android'})
        self.assertIn('data_only_devices=1/2', self._payload_lines(logs)[0])


class TestSendingThePayload(unittest.TestCase):

    def _send(self, notifications, platform='android', history=None, tokens=('tok',), data_only_tokens=None):
        loop = asyncio.new_event_loop()
        try:
            with patch('app.poller.get_firebase_app'), \
                    patch('firebase_admin.messaging.send_each') as send_each:
                loop.run_until_complete(send_push_notifications(
                    notifications, list(tokens), loop, platform=platform, history=history,
                    data_only_tokens=data_only_tokens))
        finally:
            loop.close()
        return send_each.call_args[0][0]

    def test_each_device_gets_the_shape_it_registered(self):
        sent = self._send([{'title': 'Sword', 'body': 'Got sword', 'type': 'item_progression'}],
                          tokens=('new-app', 'old-app'), data_only_tokens={'new-app'}, history='{"v":1}')

        by_token = {m.token: m for m in sent}
        self.assertIsNone(by_token['new-app'].notification)
        self.assertEqual(by_token['new-app'].data['title'], 'Sword')
        self.assertEqual(by_token['new-app'].data['history'], '{"v":1}')
        self.assertIsNotNone(by_token['old-app'].notification)
        self.assertEqual(by_token['old-app'].data['history'], '{"v":1}')

    def test_android_messages_carry_it(self):
        sent = self._send([
            {'title': 'Sword - [Room]', 'body': 'Got sword', 'type': 'item_progression'},
            {'title': 'Shield - [Room]', 'body': 'Got shield', 'type': 'item_useful'},
        ], history='{"v":1}')

        self.assertEqual([m.data.get('history') for m in sent], ['{"v":1}', '{"v":1}'])

    def test_ios_messages_do_not(self):
        sent = self._send([{'title': 'Sword', 'body': 'Got sword', 'type': 'item_progression'}],
                          platform='ios', history='{"v":1}')

        self.assertNotIn('history', sent[0].data)

    def test_left_out_when_it_would_not_fit(self):
        too_big = '{"v":1,"pad":"' + 'x' * FCM_MESSAGE_BUDGET_BYTES + '"}'
        sent = self._send([{'title': 'Sword', 'body': 'Got sword', 'type': 'item_progression'}],
                          history=too_big)

        self.assertNotIn('history', sent[0].data)
        self.assertEqual(sent[0].data['notification_type'], 'item_progression')

    def test_budget_counts_the_whole_message(self):
        data = {'notification_type': 'item_progression', 'bundled_items': 'x' * 3200}
        self.assertTrue(fits_in_push('t', 'b', {}, 'y' * 500))
        self.assertFalse(fits_in_push('t', 'b', data, 'y' * 500))
        # Bytes, not characters: names in other scripts take more than one byte each.
        self.assertFalse(fits_in_push('t', 'b', {}, 'é' * (FCM_MESSAGE_BUDGET_BYTES // 2 + 1)))


if __name__ == '__main__':
    unittest.main()
