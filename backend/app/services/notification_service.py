import logging
from firebase_admin import messaging
from app import get_firebase_app

def map_notification_to_channel_id(notif):
    """
    Maps an internal notification dictionary to an Android notification channel ID.
    Channels:
      - channel_progression: Progression items and milestone groups
      - channel_non_progression: Useful items, traps, and filler items
      - channel_hints: Hints created or found
      - channel_general: Game completion, system events, test notifications, fallback
    """
    notif_type = notif.get('type', '')
    if notif_type in ('item_progression', 'item_milestone'):
        return 'channel_progression'
    elif notif_type in ('item_useful', 'item_trap', 'item_filler'):
        return 'channel_non_progression'
    elif notif_type == 'hint':
        return 'channel_hints'
    else:
        return 'channel_general'

def send_fcm_notifications(tokens, notifications, platform='android', data_only_tokens=None):
    """
    Dispatches FCM push notifications to a list of device tokens.

    Each platform is sent through its own Firebase app, so `platform` selects both
    the app and the per-platform message config. It defaults to 'android' because
    every caller predating the Cheese demotion path passes Android tokens only.
    `data_only_tokens` are the tokens whose app takes data-only pushes (#501).
    """
    # Here, not at the top: push_message imports map_notification_to_channel_id from this module.
    from app.services.push_message import build_message

    if not tokens or not notifications:
        return 0

    platform = (platform or 'android').lower().strip()
    if platform not in ['android', 'ios']:
        platform = 'android'

    firebase_app = get_firebase_app(platform=platform)
    if not firebase_app:
        return 0

    data_only_tokens = data_only_tokens or set()
    success_count = 0

    for token in tokens:
        for notif in notifications:
            try:
                message = build_message(notif, token, platform, data_only=token in data_only_tokens)
                messaging.send(message, app=firebase_app)
                success_count += 1
            except Exception as e:
                logging.error(f"[FCM_ERROR] Failed to send push to token {token[:10]}...: {e}")

    return success_count
