import logging
import json
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

def send_fcm_notifications(tokens, notifications, platform='android'):
    """
    Dispatches FCM push notifications to a list of device tokens.

    Each platform is sent through its own Firebase app, so `platform` selects both
    the app and the per-platform message config. It defaults to 'android' because
    every caller predating the Cheese demotion path passes Android tokens only.
    """
    if not tokens or not notifications:
        return 0

    platform = (platform or 'android').lower().strip()
    if platform not in ['android', 'ios']:
        platform = 'android'

    firebase_app = get_firebase_app(platform=platform)
    if not firebase_app:
        return 0

    success_count = 0

    for token in tokens:
        for notif in notifications:
            try:
                channel_id = map_notification_to_channel_id(notif)
                priority = 'high' if channel_id == 'channel_progression' else 'normal'
                data_payload = {
                    'notification_type': str(notif.get('type', '')),
                    'channel_id': channel_id
                }
                if 'bundled_items' in notif:
                    data_payload['bundled_items'] = notif['bundled_items']
                if 'bundle_type' in notif:
                    data_payload['bundle_type'] = notif['bundle_type']

                android_config = None
                apns_config = None
                if platform == 'android':
                    android_config = messaging.AndroidConfig(
                        notification=messaging.AndroidNotification(
                            channel_id=channel_id
                        ),
                        priority=priority
                    )
                else:
                    apns_config = messaging.APNSConfig(
                        headers={'apns-priority': '10'},
                        payload=messaging.APNSPayload(
                            aps=messaging.Aps(
                                alert=messaging.ApsAlert(
                                    title=notif['title'],
                                    body=notif['body']
                                ),
                                sound='default',
                                badge=1,
                                content_available=True
                            )
                        )
                    )

                message = messaging.Message(
                    notification=messaging.Notification(
                        title=notif['title'],
                        body=notif['body']
                    ),
                    android=android_config,
                    apns=apns_config,
                    data=data_payload,
                    token=token
                )
                messaging.send(message, app=firebase_app)
                success_count += 1
            except Exception as e:
                logging.error(f"[FCM_ERROR] Failed to send push to token {token[:10]}...: {e}")

    return success_count
