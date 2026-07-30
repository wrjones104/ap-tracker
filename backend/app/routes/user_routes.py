import logging
import json
import jwt

from flask import Blueprint, request, jsonify, current_app

from firebase_admin import messaging
from datetime import datetime, timezone

from app import Session, get_firebase_app
from app.models import User, Device, JWTBlocklist
from app.routes.common import log_api_call, token_required, handle_db_errors, format_iso_z

user_bp = Blueprint('user_routes', __name__)

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

    if not fcm_token:
        return jsonify({'error': 'Missing fcm_token'}), 400

    session = Session()

    stale_devices = session.query(Device).filter(
        Device.fcm_token == fcm_token,
        Device.user_id != current_user.id
    ).all()

    if stale_devices:
        for stale in stale_devices:
            logging.info(f"[API] Unlinking FCM token from old User {stale.user_id} to assign to Current User {current_user.id}")
            session.delete(stale)

    device = None
    if device_id:
        device = session.query(Device).filter_by(
            user_id=current_user.id,
            android_id=device_id,
            platform=platform
        ).first()

        if device:
            if device.fcm_token != fcm_token:
                device.fcm_token = fcm_token
                logging.info(f"[API] Refreshed FCM token for existing device ({platform.capitalize()} ID: {device_id}) for user {current_user.id}")
        else:
            device = Device(
                fcm_token=fcm_token, 
                user_id=current_user.id, 
                android_id=device_id,
                platform=platform
            )
            session.add(device)
            logging.info(f"[API] Registered new device ({platform.capitalize()} ID: {device_id}) for user {current_user.id}")
    else:
        device = session.query(Device).filter_by(fcm_token=fcm_token, user_id=current_user.id).first()
        if not device:
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
            'use_condensed_messages_default': current_user.use_condensed_messages_default,
            'notify_hints_remote_items_default': current_user.notify_hints_remote_items_default,
            'combine_notifications_default': current_user.combine_notifications_default,
            'suppress_own_events_default': current_user.suppress_own_events_default,
            'remove_emojis_default': current_user.remove_emojis_default,
            'suppress_self_found_default': current_user.suppress_self_found_default,
            'suppress_connected_default': current_user.suppress_connected_default,
            'is_cheese_connected': current_user.cheese_api_key is not None,
            'ui_show_finished_default': current_user.ui_show_finished_default,
            'ui_show_found_hints_default': current_user.ui_show_found_hints_default,
            'ui_show_progression_default': current_user.ui_show_progression_default,
            'ui_show_useful_default': current_user.ui_show_useful_default,
            'ui_show_filler_default': current_user.ui_show_filler_default,
            'ui_show_trap_default': current_user.ui_show_trap_default,
            'is_guest': True,
            'global_snooze_until': format_iso_z(current_user.global_snooze_until),
            'is_syncing_cheese': getattr(current_user, 'is_syncing_cheese', False)
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
            'use_condensed_messages_default': current_user.use_condensed_messages_default,
            'notify_hints_remote_items_default': current_user.notify_hints_remote_items_default,
            'combine_notifications_default': current_user.combine_notifications_default,
            'suppress_own_events_default': current_user.suppress_own_events_default,
            'remove_emojis_default': current_user.remove_emojis_default,
            'suppress_self_found_default': current_user.suppress_self_found_default,
            'suppress_connected_default': current_user.suppress_connected_default,
            'is_cheese_connected': current_user.cheese_api_key is not None,
            'ui_show_finished_default': current_user.ui_show_finished_default,
            'ui_show_found_hints_default': current_user.ui_show_found_hints_default,
            'ui_show_progression_default': current_user.ui_show_progression_default,
            'ui_show_useful_default': current_user.ui_show_useful_default,
            'ui_show_filler_default': current_user.ui_show_filler_default,
            'ui_show_trap_default': current_user.ui_show_trap_default,
            'is_guest': False,
            'global_snooze_until': format_iso_z(current_user.global_snooze_until),
            'is_syncing_cheese': getattr(current_user, 'is_syncing_cheese', False)
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
    get_firebase_app()
    session = Session()
    try:
        devices = session.query(Device).filter_by(user_id=current_user.id).all()
        if not devices:
            return jsonify({'error': 'No devices registered. Open the app to register.'}), 404

        tokens = [d.fcm_token for d in devices]
        success_count = 0
        
        for token in tokens:
            try:
                message = messaging.Message(
                    notification=messaging.Notification(
                        title="Test Notification",
                        body="This is a test bundle! Click me to see the sheet."
                    ),
                    data={
                        'bundled_items': json.dumps(["Test Sword", "Debug Shield", "Potion of Coding"])
                    },
                    token=token
                )
                messaging.send(message)
                success_count += 1
            except Exception as e:
                logging.error(f"[API_WARN] Failed to send test push to token {token[:10]}...: {e}")

        return jsonify({'message': f'Sent test notification to {success_count} devices.'})
    finally:
        Session.remove()
