import logging
import json
import threading
import jwt
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from flask import Blueprint, request, jsonify, current_app

from firebase_admin import messaging
from datetime import datetime, timezone

from app import Session, get_firebase_app
from app.models import User, Device, JWTBlocklist
from app.routes.common import log_api_call, token_required, handle_db_errors, format_iso_z
from app.utils import VALID_FINISHED_DEFINITIONS

user_bp = Blueprint('user_routes', __name__)

# Valid Cheese Tracker per-user ping preferences (wire values from CT's
# ping_preference enum). Used to validate cheese_default_ping updates.
VALID_CHEESE_PING_PREFERENCES = {'liberally', 'sparingly', 'hints', 'see_notes', 'never'}

# Registration checks a token with an FCM dry run (#364). The app registers on
# every launch, and firebase_admin waits up to 120 s by default, so the check
# runs on its own small pool and the request waits at most this long. When the
# pool is busy (FCM slow or down) the check is skipped. Either way the token is
# stored as it always was: the check can only refuse a token FCM has
# positively said is dead.
_TOKEN_CHECK_TIMEOUT_SECONDS = 3
_TOKEN_CHECK_WORKERS = 4
_token_check_pool = ThreadPoolExecutor(max_workers=_TOKEN_CHECK_WORKERS, thread_name_prefix='fcm-token-check')
_token_check_slots = threading.BoundedSemaphore(_TOKEN_CHECK_WORKERS)


def is_unregistered_token_error(exc):
    """FCM's explicit UNREGISTERED answer, the same rule the poller prunes on.

    Not any NotFoundError: a bare 404 from a wrong project or endpoint would
    otherwise prune live devices. See #389.
    """
    return isinstance(exc, messaging.UnregisteredError)


def _dry_run(fcm_token, firebase_app):
    try:
        messaging.send(messaging.Message(token=fcm_token), dry_run=True, app=firebase_app)
        return False
    finally:
        _token_check_slots.release()


def fcm_token_is_dead(fcm_token, platform):
    """True only when an FCM dry run says the token is no longer registered.

    A dry run delivers nothing. No credentials, a slow or failing FCM, or any
    other error fails open and returns False.
    """
    firebase_app = get_firebase_app(platform=platform)
    if not firebase_app:
        return False
    if not _token_check_slots.acquire(blocking=False):
        logging.warning("[API] Skipping FCM token check: earlier checks are still waiting on FCM.")
        return False
    try:
        future = _token_check_pool.submit(_dry_run, fcm_token, firebase_app)
    except Exception as e:
        _token_check_slots.release()
        logging.warning(f"[API] Could not start FCM token check ({type(e).__name__}: {e}); storing the token unchecked.")
        return False
    try:
        return future.result(timeout=_TOKEN_CHECK_TIMEOUT_SECONDS)
    except FutureTimeout:
        logging.warning(f"[API] FCM token check took over {_TOKEN_CHECK_TIMEOUT_SECONDS}s; storing the token unchecked.")
        return False
    except messaging.UnregisteredError:
        # Only FCM's explicit UNREGISTERED detail. A bare 404 (wrong project,
        # bad URL) would otherwise refuse every registration.
        return True
    except Exception as e:
        logging.warning(f"[API] FCM token check failed ({type(e).__name__}: {e}); storing the token unchecked.")
        return False

@user_bp.route('/devices', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def register_device(current_user):
    data = request.json or {}
    fcm_token = data.get('fcm_token')
    device_id = data.get('device_id') or data.get('android_id') 
    platform = str(data.get('platform') or 'android').lower().strip()
    if platform not in ['android', 'ios']:
        platform = 'android'

    if not isinstance(fcm_token, str) or not fcm_token.strip():
        return jsonify({'error': 'Missing fcm_token'}), 400

    # A device restored from a backup or transfer can carry the old install's
    # cached token, which FCM has already retired. Storing it only gets it
    # pruned at the next send, and the app registers it again at next launch,
    # so the user silently gets nothing. Refuse it with a code the app can act
    # on: delete its token and register a fresh one (#364). An older app just
    # logs the failure, which leaves it where it already was. The app must
    # retry at most once per launch, so a wrong 410 cannot become a loop.
    if fcm_token_is_dead(fcm_token, platform):
        logging.info(f"[API] Refused a dead FCM token for user {current_user.id} device {device_id or 'legacy'}")
        # Any row still holding it would only be pruned at the next send.
        session = Session()
        session.query(Device).filter(Device.fcm_token == fcm_token).delete(synchronize_session=False)
        session.commit()
        return jsonify({
            'error': 'fcm_token_unregistered',
            'message': 'This push token is no longer valid. Request a new one and register again.',
        }), 410

    session = Session()

    device = None
    if device_id:
        device = session.query(Device).filter_by(
            user_id=current_user.id,
            android_id=device_id,
            platform=platform
        ).first()
    else:
        device = session.query(Device).filter_by(fcm_token=fcm_token, user_id=current_user.id).first()

    # A token is unique across all devices, so any other row holding it has to
    # go before this device can take it: another account on the same phone, or
    # this account's row for an old device ID after a phone transfer (#365).
    stale_devices = session.query(Device).filter(Device.fcm_token == fcm_token)
    if device is not None:
        stale_devices = stale_devices.filter(Device.id != device.id)
    stale_devices = stale_devices.all()

    if stale_devices:
        for stale in stale_devices:
            logging.info(f"[API] Moving FCM token from User {stale.user_id} device {stale.android_id or 'legacy'} to User {current_user.id} device {device_id or 'legacy'}")
            session.delete(stale)
        # The unit of work runs INSERT/UPDATE before DELETE within a table, so
        # without this flush the new row collides with the one being removed.
        session.flush()

    if device:
        if device.fcm_token != fcm_token:
            device.fcm_token = fcm_token
            logging.info(f"[API] Refreshed FCM token for existing device ({platform.capitalize()} ID: {device_id}) for user {current_user.id}")
    elif device_id:
        device = Device(
            fcm_token=fcm_token,
            user_id=current_user.id,
            android_id=device_id,
            platform=platform
        )
        session.add(device)
        logging.info(f"[API] Registered new device ({platform.capitalize()} ID: {device_id}) for user {current_user.id}")
    else:
        device = Device(fcm_token=fcm_token, user_id=current_user.id, platform=platform)
        session.add(device)
        logging.info(f"[API] Registered new device (legacy) for user {current_user.id}")

    session.commit()
    return jsonify({'message': 'Device registered successfully'}), 201

@user_bp.route('/devices', methods=['DELETE'])
@handle_db_errors
@log_api_call
@token_required
def unregister_device(current_user):
    data = request.json or {}
    fcm_token = data.get('fcm_token')

    if not fcm_token:
        return jsonify({'error': 'Missing fcm_token'}), 400

    session = Session()
    try:
        device = session.query(Device).filter_by(
            user_id=current_user.id,
            fcm_token=fcm_token
        ).first()

        if not device:
            logging.info(f"[API] Device {fcm_token} not found for user {current_user.id}, cannot unregister.")
            return jsonify({'message': 'Device not found'}), 404

        session.delete(device)
        session.commit()
        logging.info(f"[API] User {current_user.id} unregistered device {fcm_token}.")
        return jsonify({'message': 'Device unregistered successfully'}), 200

    except Exception as e:
        session.rollback()
        logging.error(f"Failed to unregister device for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'error': 'An internal server error occurred.'}), 500
    finally:
        Session.remove()

@user_bp.route('/users/me', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_current_user(current_user):
    if current_user.is_guest:
        return jsonify({
            'discord_id': None,
            'discord_username': 'Guest',
            'avatar_url': None,
            'notify_progression_default': current_user.notify_progression_default,
            'notify_useful_default': current_user.notify_useful_default,
            'notify_filler_default': current_user.notify_filler_default,
            'notify_trap_default': current_user.notify_trap_default,
            'notify_hints_default': current_user.notify_hints_default,
            'notify_finished_default': current_user.notify_finished_default,
            'finished_definition_default': current_user.finished_definition_default,
            'use_condensed_messages_default': current_user.use_condensed_messages_default,
            'notify_hints_remote_items_default': current_user.notify_hints_remote_items_default,
            'combine_notifications_default': current_user.combine_notifications_default,
            'suppress_own_events_default': current_user.suppress_own_events_default,
            'remove_emojis_default': current_user.remove_emojis_default,
            'suppress_self_found_default': current_user.suppress_self_found_default,
            'suppress_connected_default': current_user.suppress_connected_default,
            'is_cheese_connected': current_user.cheese_api_key is not None,
            'cheese_default_ping': current_user.cheese_default_ping,
            'ui_show_finished_default': current_user.ui_show_finished_default,
            'ui_show_found_hints_default': current_user.ui_show_found_hints_default,
            'ui_show_progression_default': current_user.ui_show_progression_default,
            'ui_show_useful_default': current_user.ui_show_useful_default,
            'ui_show_filler_default': current_user.ui_show_filler_default,
            'ui_show_trap_default': current_user.ui_show_trap_default,
            'is_guest': True,
            'global_snooze_until': format_iso_z(current_user.global_snooze_until),
            'is_syncing_cheese': getattr(current_user, 'is_syncing_cheese', False),
            # Slots the last Cheese sync moved from Playing to Watching.
            'cheese_last_sync_demoted': getattr(current_user, 'cheese_last_sync_demoted', 0) or 0,
            # Linked rooms the last sync could not find on the Cheese dashboard.
            # Reported, never acted on: the rooms stay put and the app flags them.
            'cheese_last_sync_unlisted': getattr(current_user, 'cheese_last_sync_unlisted', 0) or 0,
            # Default for the add-room dialog's "Also create this on Cheese
            # Tracker" checkbox, not a sync mode.
            'cheese_publish_new_rooms': getattr(current_user, 'cheese_publish_new_rooms', True),
            'cheese_last_sync': format_iso_z(getattr(current_user, 'cheese_last_sync', None))
        })
    else:
        base_url = "https://cdn.discordapp.com"
        avatar_url = None
        if current_user.discord_avatar_hash:
            avatar_url = f"{base_url}/avatars/{current_user.discord_id}/{current_user.discord_avatar_hash}.png"
        else:
            try:
                discriminator_int = int(current_user.discord_username.split('#')[-1]) % 5
            except (ValueError, IndexError):
                discriminator_int = 0
            avatar_url = f"{base_url}/embed/avatars/{discriminator_int}.png"

        return jsonify({
            'discord_id': current_user.discord_id,
            'discord_username': current_user.discord_username, 
            'avatar_url': avatar_url,
            'notify_progression_default': current_user.notify_progression_default,
            'notify_useful_default': current_user.notify_useful_default,
            'notify_filler_default': current_user.notify_filler_default,
            'notify_trap_default': current_user.notify_trap_default,
            'notify_hints_default': current_user.notify_hints_default,
            'notify_finished_default': current_user.notify_finished_default,
            'finished_definition_default': current_user.finished_definition_default,
            'use_condensed_messages_default': current_user.use_condensed_messages_default,
            'notify_hints_remote_items_default': current_user.notify_hints_remote_items_default,
            'combine_notifications_default': current_user.combine_notifications_default,
            'suppress_own_events_default': current_user.suppress_own_events_default,
            'remove_emojis_default': current_user.remove_emojis_default,
            'suppress_self_found_default': current_user.suppress_self_found_default,
            'suppress_connected_default': current_user.suppress_connected_default,
            'is_cheese_connected': current_user.cheese_api_key is not None,
            'cheese_default_ping': current_user.cheese_default_ping,
            'ui_show_finished_default': current_user.ui_show_finished_default,
            'ui_show_found_hints_default': current_user.ui_show_found_hints_default,
            'ui_show_progression_default': current_user.ui_show_progression_default,
            'ui_show_useful_default': current_user.ui_show_useful_default,
            'ui_show_filler_default': current_user.ui_show_filler_default,
            'ui_show_trap_default': current_user.ui_show_trap_default,
            'is_guest': False,
            'global_snooze_until': format_iso_z(current_user.global_snooze_until),
            'is_syncing_cheese': getattr(current_user, 'is_syncing_cheese', False),
            # Slots the last Cheese sync moved from Playing to Watching.
            'cheese_last_sync_demoted': getattr(current_user, 'cheese_last_sync_demoted', 0) or 0,
            # Linked rooms the last sync could not find on the Cheese dashboard.
            # Reported, never acted on: the rooms stay put and the app flags them.
            'cheese_last_sync_unlisted': getattr(current_user, 'cheese_last_sync_unlisted', 0) or 0,
            # Default for the add-room dialog's "Also create this on Cheese
            # Tracker" checkbox, not a sync mode.
            'cheese_publish_new_rooms': getattr(current_user, 'cheese_publish_new_rooms', True),
            'cheese_last_sync': format_iso_z(getattr(current_user, 'cheese_last_sync', None))
        })

@user_bp.route('/users/me/preferences', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_user_preferences(current_user):
    data = request.json or {}
    session = Session()
    try:
        user = session.query(User).filter_by(id=current_user.id).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        if 'notify_progression' in data:
            setattr(user, 'notify_progression_default', bool(data['notify_progression']))
        if 'notify_useful' in data:
            setattr(user, 'notify_useful_default', bool(data['notify_useful']))
        if 'notify_filler' in data:
            setattr(user, 'notify_filler_default', bool(data['notify_filler']))
        if 'notify_trap' in data:
            setattr(user, 'notify_trap_default', bool(data['notify_trap']))
        if 'notify_hints' in data:
            setattr(user, 'notify_hints_default', bool(data['notify_hints']))
        if 'notify_finished' in data:
            setattr(user, 'notify_finished_default', bool(data['notify_finished']))
        if 'notify_hints_remote_items' in data:
            setattr(user, 'notify_hints_remote_items_default', bool(data['notify_hints_remote_items']))
        # Validated rather than bool()-coerced: this one is an enum string.
        if 'finished_definition' in data:
            val = data['finished_definition']
            if val not in VALID_FINISHED_DEFINITIONS:
                return jsonify({'error': 'Invalid finished_definition.'}), 400
            setattr(user, 'finished_definition_default', val)
        if 'use_condensed_messages' in data:
            setattr(user, 'use_condensed_messages_default', bool(data['use_condensed_messages']))
        if 'ui_show_finished' in data:
            setattr(user, 'ui_show_finished_default', bool(data['ui_show_finished']))
        if 'ui_show_found_hints' in data:
            setattr(user, 'ui_show_found_hints_default', bool(data['ui_show_found_hints']))
        if 'ui_show_progression' in data:
            setattr(user, 'ui_show_progression_default', bool(data['ui_show_progression']))
        if 'ui_show_useful' in data:
            setattr(user, 'ui_show_useful_default', bool(data['ui_show_useful']))
        if 'ui_show_filler' in data:
            setattr(user, 'ui_show_filler_default', bool(data['ui_show_filler']))
        if 'ui_show_trap' in data:
            setattr(user, 'ui_show_trap_default', bool(data['ui_show_trap']))
        if 'combine_notifications' in data:
            setattr(user, 'combine_notifications_default', bool(data['combine_notifications']))
        if 'suppress_own_events' in data:
            setattr(user, 'suppress_own_events_default', bool(data['suppress_own_events']))
        if 'remove_emojis' in data:
            setattr(user, 'remove_emojis_default', bool(data['remove_emojis']))
        if 'suppress_self_found' in data:
            setattr(user, 'suppress_self_found_default', bool(data['suppress_self_found']))
        if 'suppress_connected' in data:
            setattr(user, 'suppress_connected_default', bool(data['suppress_connected']))
        if 'cheese_default_ping' in data:
            raw = data['cheese_default_ping']
            # Empty string / null clears the default (revert to leaving CT's value alone).
            if raw is None or (isinstance(raw, str) and raw.strip() == ''):
                user.cheese_default_ping = None
            elif isinstance(raw, str) and raw.strip().lower() in VALID_CHEESE_PING_PREFERENCES:
                user.cheese_default_ping = raw.strip().lower()
            else:
                return jsonify({'error': 'Invalid cheese_default_ping value.'}), 400
        if 'cheese_publish_new_rooms' in data:
            setattr(user, 'cheese_publish_new_rooms', bool(data['cheese_publish_new_rooms']))
        session.commit()
        return jsonify({'message': 'Preferences updated successfully'}), 200
    except Exception as e:
        session.rollback()
        logging.error(f"Failed to update preferences for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'error': 'An internal server error occurred.'}), 500
    finally:
        Session.remove()

@user_bp.route('/users/me', methods=['DELETE'])
@handle_db_errors
@log_api_call
@token_required
def delete_current_user(current_user):
    session = Session()
    try:
        token = request.headers['Authorization'].split(" ")[1]
        secret = current_app.config['SECRET_KEY']
        try:
            data = jwt.decode(token, secret, algorithms=['HS256'], options={"verify_exp": False})
            jti = data.get('jti')
            exp = data.get('exp')
            if jti and exp:
                expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
                session.add(JWTBlocklist(jti=jti, expires_at=expires_at))
        except (jwt.InvalidTokenError, KeyError, TypeError) as e:
            logging.warning(f"Could not blocklist token during account deletion for user {current_user.id}: {e}")

        session.delete(current_user)
        session.commit()
        logging.info(f"[API] User {current_user.id} ({current_user.discord_username}) has deleted their account.")
        return jsonify({'message': 'Account deleted successfully'}), 200
    except Exception as e:
        session.rollback()
        logging.error(f"Failed to delete account for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'error': 'An internal server error occurred.'}), 500
    finally:
        Session.remove()

@user_bp.route('/users/me/test-notification', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def send_test_notification(current_user):
    session = Session()
    try:
        devices = session.query(Device).filter_by(user_id=current_user.id).all()
        if not devices:
            return jsonify({'error': 'No devices registered. Open the app to register.'}), 404

        success_count = 0
        dead_devices = []

        for device in devices:
            token = device.fcm_token
            # Each platform has its own Firebase project. Sending through the
            # wrong one could answer 404 and prune a live device.
            firebase_app = get_firebase_app(platform=device.platform)
            if not firebase_app:
                logging.warning(f"[API_WARN] Skipping test push to token {token[:10]}...: no Firebase app for '{device.platform}'.")
                continue
            try:
                message = messaging.Message(
                    notification=messaging.Notification(
                        title="Test Notification",
                        body="This is a test bundle! Click me to see the sheet."
                    ),
                    android=messaging.AndroidConfig(
                        notification=messaging.AndroidNotification(
                            channel_id="channel_general"
                        ),
                        priority='high'
                    ),
                    data={
                        'bundled_items': json.dumps(["Test Sword", "Debug Shield", "Potion of Coding"]),
                        'notification_type': 'test',
                        'channel_id': 'channel_general'
                    },
                    token=token
                )
                messaging.send(message, app=firebase_app)
                success_count += 1
            except Exception as e:
                logging.error(f"[API_WARN] Failed to send test push to token {token[:10]}...: {e}")
                if is_unregistered_token_error(e):
                    dead_devices.append(device)

        # Pruned here as the poller would, so the test does not report a device
        # that can never receive anything (#364).
        # A bulk delete, like the poller's, so a row another request already
        # pruned is simply skipped.
        for device in dead_devices:
            logging.info(f"[FCM] Removing dead token for user {current_user.id} device {device.android_id or 'legacy'} after a test push.")
        if dead_devices:
            session.query(Device).filter(Device.id.in_([d.id for d in dead_devices])).delete(synchronize_session=False)
            session.commit()

        return jsonify({
            'message': f'Sent test notification to {success_count} devices.',
            'sent': success_count,
            'failed': len(devices) - success_count,
            'removed': len(dead_devices),
        })
    finally:
        Session.remove()
