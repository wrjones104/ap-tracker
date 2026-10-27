"""
Tests for push_message, the one place FCM messages are built.

Two shapes (#501): the notification message every installed app gets, and the data-only
message for devices whose app draws it itself. Plus the size rules: a combined push's bundle
list is trimmed to fit FCM's limit instead of getting the whole push refused (#499), and the
item payload (#416) rides only on what is left.
"""
import os

# Before `app` is imported, which binds its engine once per process: whichever way these tests
# are loaded, they never reach the database backend/.env names (see backend/tests/__init__.py).
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'test_push_message.db'))

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from firebase_admin import exceptions, messaging

from app.services.push_history import FCM_MESSAGE_BUDGET_BYTES, message_size
from app.services.push_message import build_data, build_message, history_fits, log_failed_sends

ITEM = {'title': 'Master Sword - [Room]', 'body': 'Sent to Link by Samus', 'type': 'item_progression'}


def _bundle(n):
    return dict(ITEM, title=f'New Items ({n}) - [Room]', body='Master Sword, …',
                bundled_items=json.dumps([f"Progressive Sword [Hero (Link)] #{i}" for i in range(n)]))


class TestMessageShapes(unittest.TestCase):

    def setUp(self):
        env = patch.dict(os.environ, {'DATA_ONLY_PUSH': ''})
        env.start()
        self.addCleanup(env.stop)

    def test_a_device_that_did_not_ask_gets_todays_message(self):
        msg = build_message(ITEM, 'tok', 'android')

        self.assertEqual(msg.notification.title, ITEM['title'])
        self.assertEqual(msg.android.notification.channel_id, 'channel_progression')
        self.assertEqual(msg.android.priority, 'high')
        self.assertNotIn('title', msg.data)
        self.assertEqual(msg.data['notification_type'], 'item_progression')

    def test_a_data_only_device_gets_title_and_body_in_the_data(self):
        msg = build_message(ITEM, 'tok', 'android', data_only=True)

        self.assertIsNone(msg.notification)
        self.assertIsNone(msg.android.notification)
        self.assertEqual(msg.android.priority, 'high')
        self.assertEqual(msg.data['title'], ITEM['title'])
        self.assertEqual(msg.data['body'], ITEM['body'])
        self.assertEqual(msg.data['channel_id'], 'channel_progression')

    def test_priority_follows_the_channel_in_both_shapes(self):
        useful = dict(ITEM, type='item_useful')
        self.assertEqual(build_message(useful, 'tok', 'android').android.priority, 'normal')
        self.assertEqual(build_message(useful, 'tok', 'android', data_only=True).android.priority, 'normal')

    def test_ios_never_gets_data_only(self):
        msg = build_message(ITEM, 'tok', 'ios', data_only=True)

        self.assertIsNotNone(msg.notification)
        self.assertEqual(msg.apns.payload.aps.alert.title, ITEM['title'])
        self.assertNotIn('title', msg.data)

    def test_the_kill_switch_sends_everyone_todays_message(self):
        for off in ('0', 'false', 'OFF', 'no'):
            with self.subTest(off=off), patch.dict(os.environ, {'DATA_ONLY_PUSH': off}):
                msg = build_message(ITEM, 'tok', 'android', data_only=True)
                self.assertIsNotNone(msg.notification)
                self.assertNotIn('title', msg.data)

    def test_overrides_for_pushes_that_are_not_item_events(self):
        conflict = {'title': 'Slot Already Claimed', 'body': '…', 'type': 'conflict'}
        msg = build_message(conflict, 'tok', 'android', data_only=True,
                            channel_id='channel_general', priority='high')

        self.assertEqual(msg.android.priority, 'high')
        self.assertEqual(msg.data['channel_id'], 'channel_general')


class TestSizes(unittest.TestCase):

    def test_a_small_bundle_is_left_alone(self):
        content = _bundle(3)
        data, _ = build_data(content)

        self.assertEqual(data['bundled_items'], content['bundled_items'])
        self.assertEqual(data['bundle_type'], 'item_progression')

    def test_a_bundle_too_big_for_fcm_is_trimmed_to_fit(self):
        # About 130 of these were refused by FCM before (#499).
        content = _bundle(200)

        for data_only in (False, True):
            with self.subTest(data_only=data_only):
                msg = build_message(content, 'tok', 'android', data_only=data_only)
                kept = json.loads(msg.data['bundled_items'])
                self.assertLess(len(kept), 200)
                self.assertEqual(kept[-1], f"…and {200 - (len(kept) - 1)} more")
                self.assertEqual(kept[0], "Progressive Sword [Hero (Link)] #0")
                title = '' if data_only else content['title']
                body = '' if data_only else content['body']
                self.assertLessEqual(message_size(title, body, msg.data), FCM_MESSAGE_BUDGET_BYTES)

    def test_the_payload_rides_only_on_what_the_bundle_leaves(self):
        history = json.dumps({'v': 1, 'pad': 'x' * 1000})
        self.assertTrue(history_fits(_bundle(3), history))
        # A trimmed bundle fills the message, so the payload stays off and the app syncs.
        self.assertFalse(history_fits(_bundle(200), history))
        self.assertNotIn('history', build_message(_bundle(200), 'tok', 'android', history=history).data)

    def test_data_only_counts_title_and_body_once(self):
        # Title and body move into the data; counting them again there would refuse payloads
        # that fit.
        content = dict(ITEM, title='T' * 400, body='B' * 400)
        base, _ = build_data(content)
        room = FCM_MESSAGE_BUDGET_BYTES - message_size(content['title'], content['body'], base) - len('history')
        # The data-only shape is the key names "title" and "body" larger, no more.
        history = 'h' * (room - len('titlebody'))

        self.assertIn('history', build_message(content, 'tok', 'android', history=history).data)
        self.assertIn('history', build_message(content, 'tok', 'android', data_only=True, history=history).data)
        self.assertTrue(history_fits(content, history))
        self.assertFalse(history_fits(content, history + 'h'))

    def test_the_payload_never_goes_to_ios(self):
        self.assertNotIn('history', build_message(ITEM, 'tok', 'ios', history='{"v":1}').data)


class TestTrimSearch(unittest.TestCase):
    """The binary search must keep exactly what walking down one entry at a time kept."""

    @staticmethod
    def _walk_down(entries, title, body, data):
        def fits(candidate):
            return message_size(title, body, dict(data, bundled_items=json.dumps(candidate))) \
                <= FCM_MESSAGE_BUDGET_BYTES
        if fits(entries):
            return entries
        for kept in range(len(entries) - 1, -1, -1):
            candidate = entries[:kept] + [f"…and {len(entries) - kept} more"]
            if fits(candidate):
                return candidate
        return [f"…and {len(entries)} more"]

    def test_same_result_as_walking_down(self):
        from app.services.push_message import _bundle_that_fits
        data = {'notification_type': 'item_progression', 'channel_id': 'channel_progression',
                'bundle_type': 'item_progression'}
        # The walk-down reference is the slow code this replaced, so the sizes stay modest.
        for count in (0, 1, 50, 99, 100, 101, 150, 400, 600):
            for width in (5, 30, 120, 4000):
                with self.subTest(count=count, width=width):
                    entries = [f"{i:04d}" + 'x' * width for i in range(count)]
                    self.assertEqual(_bundle_that_fits(entries, 'title', 'body', data),
                                     self._walk_down(entries, 'title', 'body', data))

    def test_a_release_sized_bundle_is_quick(self):
        import time
        content = _bundle(5000)
        start = time.perf_counter()
        build_data(content)
        self.assertLess(time.perf_counter() - start, 0.1)


class TestOneBlockPerShape(unittest.TestCase):

    def test_the_data_block_is_built_once_per_shape(self):
        prepared = {}
        with patch('app.services.push_message.build_data', wraps=build_data) as built:
            messages = [build_message(_bundle(200), f'tok{i}', 'android', data_only=(i % 2 == 0),
                                      prepared=prepared) for i in range(6)]

        self.assertEqual(built.call_count, 2)
        self.assertEqual(len({m.data['bundled_items'] for m in messages}), 1)
        # Each message holds its own dict.
        self.assertIsNot(messages[0].data, messages[2].data)

    @patch('app.services.notification_service.messaging.send')
    @patch('app.services.notification_service.get_firebase_app')
    def test_send_fcm_notifications_sends_each_device_its_shape(self, _app, send):
        from app.services.notification_service import send_fcm_notifications

        sent = send_fcm_notifications(['new-app', 'old-app'], [ITEM], data_only_tokens={'new-app'})

        self.assertEqual(sent, 2)
        by_token = {c.args[0].token: c.args[0] for c in send.call_args_list}
        self.assertIsNone(by_token['new-app'].notification)
        self.assertEqual(by_token['new-app'].data['title'], ITEM['title'])
        self.assertIsNotNone(by_token['old-app'].notification)


class TestFailureLogging(unittest.TestCase):

    def test_every_refusal_is_logged_by_reason(self):
        responses = [
            SimpleNamespace(success=True, exception=None),
            SimpleNamespace(success=False, exception=exceptions.InvalidArgumentError('Message is too large')),
            SimpleNamespace(success=False, exception=exceptions.InvalidArgumentError('again')),
            SimpleNamespace(success=False, exception=messaging.UnregisteredError('gone')),
        ]

        with self.assertLogs(level='ERROR') as logs:
            reasons = log_failed_sends(responses, 'poller, android')

        self.assertEqual(reasons, {'InvalidArgumentError': 2, 'UnregisteredError': 1})
        self.assertIn('3 of 4 sends failed (poller, android)', logs.output[0])

    def test_nothing_is_logged_when_all_went_through(self):
        self.assertEqual(log_failed_sends([SimpleNamespace(success=True, exception=None)], 'x'), {})


if __name__ == '__main__':
    unittest.main()
