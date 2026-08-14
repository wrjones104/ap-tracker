from unittest.mock import MagicMock, patch
import json
from app.services.notification_service import map_notification_to_channel_id, send_fcm_notifications

def test_map_notification_to_channel_id():
    # Progression & Milestones -> channel_progression
    assert map_notification_to_channel_id({'type': 'item_progression'}) == 'channel_progression'
    assert map_notification_to_channel_id({'type': 'item_milestone'}) == 'channel_progression'

    # Non-progression items (useful, trap, filler) -> channel_non_progression
    assert map_notification_to_channel_id({'type': 'item_useful'}) == 'channel_non_progression'
    assert map_notification_to_channel_id({'type': 'item_trap'}) == 'channel_non_progression'
    assert map_notification_to_channel_id({'type': 'item_filler'}) == 'channel_non_progression'

    # Hints -> channel_hints
    assert map_notification_to_channel_id({'type': 'hint'}) == 'channel_hints'

    # General / Other / Fallback -> channel_general
    assert map_notification_to_channel_id({'type': 'player_finish'}) == 'channel_general'
    assert map_notification_to_channel_id({'type': 'unknown_event'}) == 'channel_general'
    assert map_notification_to_channel_id({}) == 'channel_general'

@patch('app.services.notification_service.messaging.send')
@patch('app.services.notification_service.get_firebase_app')
def test_send_fcm_notifications_sets_android_channel(mock_get_app, mock_send):
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
    assert sent_count == 4
    assert mock_send.call_count == 4

    messages = [call.args[0] for call in mock_send.call_args_list]

    # Verify Progression message
    assert messages[0].android.notification.channel_id == 'channel_progression'
    assert messages[0].data['channel_id'] == 'channel_progression'
    assert messages[0].data['notification_type'] == 'item_progression'

    # Verify Non-Progression message
    assert messages[1].android.notification.channel_id == 'channel_non_progression'
    assert messages[1].data['channel_id'] == 'channel_non_progression'
    assert messages[1].data['notification_type'] == 'item_useful'

    # Verify Hints message
    assert messages[2].android.notification.channel_id == 'channel_hints'
    assert messages[2].data['channel_id'] == 'channel_hints'
    assert messages[2].data['notification_type'] == 'hint'

    # Verify General message
    assert messages[3].android.notification.channel_id == 'channel_general'
    assert messages[3].data['channel_id'] == 'channel_general'
    assert messages[3].data['notification_type'] == 'player_finish'
