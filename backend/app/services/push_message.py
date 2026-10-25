"""
The one place an FCM message is built, for every push the server sends.

Two shapes:
- **Notification message** (every device until its app says otherwise): a `notification` block
  plus data. While the app is in the background, Android's Firebase library draws it and the
  app's code never runs, so there are no Snooze buttons and no widget update (#501).
- **Data-only message**, for Android devices whose app registered `data_only_push` (#501): the
  title and body travel in the data, and the app draws the notification itself, in the
  background too. Installed apps read only the notification block and would show nothing for
  one of these, which is why it goes only to devices that asked for it.

`DATA_ONLY_PUSH` in the environment is the kill switch: `0`, `false`, `off` or `no` sends every
device the notification message again, without a deploy (`docker compose up -d` to apply, as
for MIN_APP_VERSION). Unset means on.

Sizes are kept inside FCM's limit here too. The bundle list a combined push carries had no cap,
so a push of roughly 130 items or more was refused as too large and never arrived (#499). It is
now trimmed to fit, with a closing entry saying how many were left out. The item payload
(#416, push_history) goes on only if what is left still fits.
"""
import functools
import json
import logging
import os

from firebase_admin import messaging

from app.services.notification_service import map_notification_to_channel_id
from app.services.push_history import FCM_MESSAGE_BUDGET_BYTES, fits_in_push, message_size

_OFF_VALUES = {'0', 'false', 'off', 'no'}


def data_only_push_enabled():
    return _parse_data_only_push(os.getenv('DATA_ONLY_PUSH', '').strip().lower())


# Cached per value, so each value is logged once rather than on every push.
@functools.lru_cache(maxsize=8)
def _parse_data_only_push(raw):
    enabled = raw not in _OFF_VALUES
    logging.info(f"[CONFIG] Data-only pushes {'on' if enabled else 'OFF'} (DATA_ONLY_PUSH={raw or 'unset'}).")
    return enabled


def _bundle_that_fits(entries, title, body, data):
    """The longest head of `entries` that fits, plus "…and N more" when any were left out."""
    def fits(candidate):
        return message_size(title, body, dict(data, bundled_items=json.dumps(candidate))) \
            <= FCM_MESSAGE_BUDGET_BYTES

    if fits(entries):
        return entries
    # A longer head never fits better, so search for it. Walking down one entry at a time
    # re-serialised the list per entry dropped: a second or more for a release-sized bundle,
    # on the poller's event loop.
    lo, hi = 0, len(entries) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(entries[:mid] + [f"…and {len(entries) - mid} more"]):
            lo = mid
        else:
            hi = mid - 1
    return entries[:lo] + [f"…and {len(entries) - lo} more"]


def build_data(content, platform='android', data_only=False, history=None,
               channel_id=None, log_trim=True):
    """
    The data block for one push, and whether the item payload made it in.

    `content` is the internal notification dict: title, body, type, and optionally
    bundled_items (a JSON list of strings) and bundle_type. `channel_id` overrides what the
    type implies, for pushes that are not item events (conflicts, the test push).
    """
    channel_id = channel_id or map_notification_to_channel_id(content)
    title, body = content.get('title') or '', content.get('body') or ''
    data = {
        'notification_type': str(content.get('type', '')),
        'channel_id': channel_id,
    }
    if data_only:
        data['title'] = title
        data['body'] = body
        # Already counted as data; the size checks below must not count them twice.
        title, body = '', ''

    if 'bundled_items' in content:
        # Before the trim, which has to count it.
        data['bundle_type'] = str(content.get('bundle_type') or content.get('type', ''))
        bundled = content['bundled_items']
        try:
            entries = json.loads(bundled)
        except (TypeError, ValueError):
            entries = None
        if isinstance(entries, list):
            kept = _bundle_that_fits(entries, title, body, data)
            if kept is not entries and log_trim:
                logging.info(f"[NOTIFIER] Bundle of {len(entries)} trimmed to fit the push (#499).")
            bundled = json.dumps(kept)
        data['bundled_items'] = bundled

    history_included = False
    if history and platform == 'android' and fits_in_push(title, body, data, history):
        data['history'] = history
        history_included = True

    return data, history_included


def history_fits(content, history):
    """
    Whether the item payload fits on this push, measured on the data-only shape: it carries
    the same text plus the `title` and `body` key names, so it is never the smaller of the two.
    """
    return build_data(content, 'android', data_only=True, history=history, log_trim=False)[1]


def build_message(content, token, platform='android', data_only=False, history=None,
                  channel_id=None, priority=None, prepared=None):
    """
    One FCM message for one device. `data_only` is what the device registered; the kill switch
    and the platform decide whether it is honoured.

    `prepared`, when given, caches the data block per shape: a caller sending the same push
    to many devices passes one dict per push, and each block is built (and its bundle trimmed)
    once rather than once per device.
    """
    platform = (platform or 'android').lower().strip()
    data_only = bool(data_only) and platform == 'android' and data_only_push_enabled()
    channel_id = channel_id or map_notification_to_channel_id(content)
    priority = priority or ('high' if channel_id == 'channel_progression' else 'normal')
    shape = (platform, data_only)
    if prepared is not None and shape in prepared:
        data = prepared[shape]
    else:
        data, _ = build_data(content, platform, data_only, history, channel_id)
        if prepared is not None:
            prepared[shape] = data
    # Each message gets its own copy: firebase_admin keeps a reference to the dict.
    data = dict(data)
    title, body = content.get('title') or '', content.get('body') or ''

    if data_only:
        return messaging.Message(
            token=token,
            data=data,
            android=messaging.AndroidConfig(priority=priority),
        )

    android_config = None
    apns_config = None
    if platform == 'android':
        android_config = messaging.AndroidConfig(
            priority=priority,
            notification=messaging.AndroidNotification(channel_id=channel_id),
        )
    else:
        apns_config = messaging.APNSConfig(
            headers={'apns-priority': '10'},
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    alert=messaging.ApsAlert(title=title, body=body),
                    sound='default',
                    badge=1,
                    content_available=True,
                )
            ),
        )
    return messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        token=token,
        android=android_config,
        apns=apns_config,
        data=data,
    )


def log_failed_sends(responses, context):
    """
    One error line per batch for every send FCM refused, counted by reason. Before this, only
    the two refusals that prune a token were logged, so a push refused as too large left no
    trace at all (#499).
    """
    reasons = {}
    for res in responses:
        if not res.success:
            name = type(res.exception).__name__ if res.exception else 'Unknown'
            reasons[name] = reasons.get(name, 0) + 1
    if reasons:
        summary = ", ".join(f"{name} x{count}" for name, count in sorted(reasons.items()))
        logging.error(f"[FCM] {sum(reasons.values())} of {len(responses)} sends failed ({context}): {summary}")
    return reasons
