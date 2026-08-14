import unittest
from unittest.mock import patch
from app.services.notification_service import map_notification_to_channel_id, send_fcm_notifications, compress_notifications


class TestNotificationChannels(unittest.TestCase):

    def test_map_notification_to_channel_id(self):
        # Progression & Milestones -> channel_progression
        self.assertEqual(map_notification_to_channel_id({'type': 'item_progression'}), 'channel_progression')
        self.assertEqual(map_notification_to_channel_id({'type': 'item_milestone'}), 'channel_progression')

        # Non-progression items (useful, trap, filler) -> channel_non_progression
        self.assertEqual(map_notification_to_channel_id({'type': 'item_useful'}), 'channel_non_progression')
        self.assertEqual(map_notification_to_channel_id({'type': 'item_trap'}), 'channel_non_progression')
        self.assertEqual(map_notification_to_channel_id({'type': 'item_filler'}), 'channel_non_progression')

        # Hints -> channel_hints
        self.assertEqual(map_notification_to_channel_id({'type': 'hint'}), 'channel_hints')

        # General / Other / Fallback -> channel_general
        self.assertEqual(map_notification_to_channel_id({'type': 'player_finish'}), 'channel_general')
        self.assertEqual(map_notification_to_channel_id({'type': 'unknown_event'}), 'channel_general')
        self.assertEqual(map_notification_to_channel_id({}), 'channel_general')

    @patch('app.services.notification_service.messaging.send')
    @patch('app.services.notification_service.get_firebase_app')
    def test_send_fcm_notifications_sets_android_channel_and_priority(self, mock_get_app, mock_send):
        tokens = ['token_123']
        notifications = [
            {
                'title': '🏆 Progressive Bow - [Room 1]',
                'body': 'Alice sent Progressive Bow to Bob',
                'type': 'item_progression'
            },
            {
                'title': '✅ Bombs - [Room 1]',
                'body': 'Alice sent Bombs to Bob',
                'type': 'item_useful'
            },
            {
                'title': '💡 Hint - [Room 1]',
                'body': 'Hookshot is at Death Mountain',
                'type': 'hint'
            },
            {
                'title': '🏁 Finished - [Room 1]',
                'body': 'Player 1 has completed their goal',
                'type': 'player_finish'
            }
        ]

        sent_count = send_fcm_notifications(tokens, notifications)
        self.assertEqual(sent_count, 4)
        self.assertEqual(mock_send.call_count, 4)

        messages = [call.args[0] for call in mock_send.call_args_list]

        # Verify Progression message: channel_progression and high priority
        self.assertEqual(messages[0].android.notification.channel_id, 'channel_progression')
        self.assertEqual(messages[0].android.priority, 'high')
        self.assertEqual(messages[0].data['channel_id'], 'channel_progression')
        self.assertEqual(messages[0].data['notification_type'], 'item_progression')

        # Verify Non-Progression message: channel_non_progression and normal priority
        self.assertEqual(messages[1].android.notification.channel_id, 'channel_non_progression')
        self.assertEqual(messages[1].android.priority, 'normal')
        self.assertEqual(messages[1].data['channel_id'], 'channel_non_progression')
        self.assertEqual(messages[1].data['notification_type'], 'item_useful')

        # Verify Hints message: channel_hints and normal priority
        self.assertEqual(messages[2].android.notification.channel_id, 'channel_hints')
        self.assertEqual(messages[2].android.priority, 'normal')
        self.assertEqual(messages[2].data['channel_id'], 'channel_hints')
        self.assertEqual(messages[2].data['notification_type'], 'hint')

        # Verify General message: channel_general and normal priority
        self.assertEqual(messages[3].android.notification.channel_id, 'channel_general')
        self.assertEqual(messages[3].android.priority, 'normal')
        self.assertEqual(messages[3].data['channel_id'], 'channel_general')
        self.assertEqual(messages[3].data['notification_type'], 'player_finish')

    def test_compress_notifications_preserves_progression_priority_in_mixed_batches(self):
        class MockUserPrefs:
            combine_notifications_default = True
            remove_emojis_default = False

        mixed_items = [
            {'title': '📃 Arrows - [Room 1]', 'body': 'Bob sent Arrows', 'type': 'item_filler'},
            {'title': '🏆 Master Sword - [Room 1]', 'body': 'Bob sent Master Sword', 'type': 'item_progression'},
            {'title': '✅ Shield - [Room 1]', 'body': 'Bob sent Shield', 'type': 'item_useful'}
        ]

        compressed = compress_notifications(mixed_items, MockUserPrefs(), {})
        self.assertEqual(len(compressed), 1)
        # Even though filler was first in the input list, the squashed batch must resolve to item_progression
        self.assertEqual(compressed[0]['type'], 'item_progression')
        self.assertEqual(map_notification_to_channel_id(compressed[0]), 'channel_progression')

    @patch('firebase_admin.messaging.send_each')
    @patch('app.poller.get_firebase_app')
    def test_poller_send_push_notifications_sets_android_channel(self, mock_get_app, mock_send_each):
        import asyncio
        from app.poller import send_push_notifications as poller_send_push

        notifications = [
            {'title': 'Sword - [Room]', 'body': 'Got sword', 'type': 'item_progression'},
            {'title': 'Shield - [Room]', 'body': 'Got shield', 'type': 'item_useful'},
            {'title': 'Hint - [Room]', 'body': 'Hint body', 'type': 'hint'}
        ]

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(poller_send_push(notifications, ['token_123'], loop, platform='android'))
        finally:
            loop.close()

        self.assertTrue(mock_send_each.called)
        sent_messages = mock_send_each.call_args[0][0]
        self.assertEqual(len(sent_messages), 3)

        # Progression
        self.assertEqual(sent_messages[0].android.notification.channel_id, 'channel_progression')
        self.assertEqual(sent_messages[0].android.priority, 'high')
        self.assertEqual(sent_messages[0].data['channel_id'], 'channel_progression')
        self.assertEqual(sent_messages[0].data['notification_type'], 'item_progression')

        # Useful
        self.assertEqual(sent_messages[1].android.notification.channel_id, 'channel_non_progression')
        self.assertEqual(sent_messages[1].android.priority, 'normal')
        self.assertEqual(sent_messages[1].data['channel_id'], 'channel_non_progression')
        self.assertEqual(sent_messages[1].data['notification_type'], 'item_useful')

        # Hint
        self.assertEqual(sent_messages[2].android.notification.channel_id, 'channel_hints')
        self.assertEqual(sent_messages[2].android.priority, 'normal')
        self.assertEqual(sent_messages[2].data['channel_id'], 'channel_hints')
        self.assertEqual(sent_messages[2].data['notification_type'], 'hint')


if __name__ == '__main__':
    unittest.main()


