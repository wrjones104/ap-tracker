import logging
import json
import os
import requests
import jwt
import asyncio
import itertools
from datetime import datetime, timezone, timedelta
from functools import wraps
from urllib.parse import urlparse
from ipaddress import ip_address
from typing import cast

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.exc import OperationalError, IntegrityError
from sqlalchemy.orm import selectinload, aliased
from sqlalchemy import or_, desc, tuple_

from . import Session
from .models import (
    User, Device, TrackedRoom, UserRoomSubscription, UserTrackedSlot, 
    DatapackageCache, NotifiedItem, NotifiedHint, JWTBlocklist, UserIgnoreItem
)

bp = Blueprint('api', __name__)

def chunked_iterable(iterable, size):
    """Yields successive chunks from an iterable."""
    it = iter(iterable)
    while True:
        chunk = tuple(itertools.islice(it, size))
        if not chunk:
            break
        yield chunk

def format_iso_z(dt_obj):
    """Formats a datetime object to ISO-8601 with strictly 'Z' for UTC."""
    if not dt_obj:
        return None
    # Ensure it is UTC aware
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    
    # Generate ISO format and swap the offset
    return dt_obj.isoformat().replace("+00:00", "Z")

def log_api_call(f):
    """A decorator to log API request and response."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Log Request
        payload = ""
        if request.is_json and request.content_length:
            try:
                payload = json.dumps(request.json)
            except Exception:
                payload = "Error dumping JSON payload"
        
        logging.debug(f"[API] Call: {request.method} {request.path} | Payload: {payload}")
        
        try:
            response = f(*args, **kwargs)
            
            response_data = ""
            if hasattr(response, 'get_data'):
                try:
                    response_data = response.get_data(as_text=True)[:500] 
                except Exception:
                    response_data = "Error getting response data"
            else:
                response_data = str(response)

            logging.debug(f"[API] Response: {request.path} | Body: {response_data}...")
            return response
        
        except Exception as e:
            logging.error(f"[API] Error: {request.path} | Exception: {e}", exc_info=True)
            raise e
            
    return decorated_function

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                logging.warning(f"Malformed Authorization header from {request.remote_addr}.")
                return jsonify({'error': 'Malformed Authorization header'}), 401

        if not token:
            logging.warning(f"Missing auth token from {request.remote_addr}.")
            return jsonify({'error': 'Authentication token is missing'}), 401

        session = None
        try:
            secret = current_app.config['SECRET_KEY']
            data = jwt.decode(token, secret, algorithms=['HS256'])

            jti = data.get('jti')
            if not jti:
                logging.warning(f"Auth failure: Token is missing 'jti' claim.")
                return jsonify({'error': 'Invalid token format'}), 401

            session = Session()

            is_blocked = session.query(JWTBlocklist).filter_by(jti=jti).first()
            if is_blocked:
                logging.warning(f"Auth failure: Blocked token used by user {data.get('user_id')}.")
                return jsonify({'error': 'Token has been revoked'}), 401

            current_user = session.query(User).filter_by(id=data['user_id']).first()
            if not current_user:
                logging.warning(f"Auth success, but user {data['user_id']} not found in DB.")
                return jsonify({'error': 'User not found'}), 401
        except jwt.ExpiredSignatureError:
            logging.info(f"Auth failure: Token has expired.")
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            logging.warning(f"Auth failure: Invalid token received.")
            return jsonify({'error': 'Invalid token'}), 401
        except Exception as e:
            if session:
                session.rollback()
            logging.error(f"Token processing error: {e}", exc_info=True)
            return jsonify({'error': 'An internal server error occurred.'}), 500
        finally:
            if session:
                Session.remove()
                
        return f(current_user, *args, **kwargs)
    return decorated_function

def handle_db_errors(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session = Session()
        try:
            result = f(*args, **kwargs)
            session.commit()
            return result
        except OperationalError as e:
            session.rollback()
            logging.error(f"[API_ERROR] Database locked or operational error: {e}")
            return jsonify({'error': 'Database is busy, please try again.'}), 503
        except IntegrityError as e:
            session.rollback()
            logging.warning(f"[API_ERROR] Database integrity error: {e}")
            return jsonify({'error': 'A record with this value already exists.'}), 409
        except Exception as e:
            session.rollback()
            logging.error(f"[API_ERROR] An unhandled API error occurred: {e}", exc_info=True)
            return jsonify({'error': 'An internal server error occurred.'}), 500
        finally:
            Session.remove()
    return decorated_function

# =============================================================================
# LOGOUT ENDPOINT
# =============================================================================

@bp.route('/logout', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def logout(current_user):
    """
    (V2) Logs the user out by adding their token's JTI to the blocklist.
    """
    token = request.headers['Authorization'].split(" ")[1]
    secret = current_app.config['SECRET_KEY']

    try:
        data = jwt.decode(token, secret, algorithms=['HS256'], options={"verify_exp": False})
    except jwt.InvalidTokenError:
        return jsonify({'error': 'Invalid token'}), 401

    jti = data.get('jti')
    exp = data.get('exp')

    if not jti or not exp:
        return jsonify({'error': 'Token is missing JTI or EXP claim'}), 400

    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)

    session = Session()
    try:
        session.add(JWTBlocklist(jti=jti, expires_at=expires_at))
        session.commit()
    except IntegrityError:
        session.rollback()
        # JTI is already in the blocklist, which is fine.
        logging.info(f"JTI {jti} for user {current_user.id} was already blocklisted.")
    except Exception as e:
        session.rollback()
        logging.error(f"Failed to add JTI to blocklist for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'error': 'Logout failed.'}), 500
    finally:
        Session.remove()

    logging.info(f"User {current_user.id} logged out successfully.")
    return jsonify({'message': 'Successfully logged out.'}), 200

# =============================================================================
# PUBLIC CONFIG ENDPOINT
# =============================================================================

@bp.route('/config', methods=['GET'])
@log_api_call 
def get_public_config():
    """
    Returns public configuration data, such as the minimum
    required app version, to all clients. This endpoint is
    unauthenticated so the app can check it on launch.
    """
    try:
        min_version = 9
        
        return jsonify({
            'min_app_version': min_version
        })
    except Exception as e:
        logging.error(f"[CONFIG_ERROR] Failed to serve /config: {e}", exc_info=True)
        return jsonify({'error': 'Could not fetch server config.'}), 500


# =============================================================================
# DEVICE MANAGEMENT
# =============================================================================

@bp.route('/devices', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def register_device(current_user):
    """
    Registers a new device (FCM token) for the current user.
    It now uses 'android_id' to uniquely identify a device and
    update its FCM token, preventing duplicate device entries.
    """
    data = request.json or {}
    fcm_token = data.get('fcm_token')
    android_id = data.get('android_id') # New ID from the app

    if not fcm_token:
        return jsonify({'error': 'Missing fcm_token'}), 400

    session = Session()
    device = None

    if android_id:
        device = session.query(Device).filter_by(
            user_id=current_user.id,
            android_id=android_id
        ).first()

        if device:
            device.fcm_token = fcm_token
            logging.info(f"[API] Refreshed FCM token for existing device (Android ID: {android_id}) for user {current_user.id}")
        else:
            device = Device(
                fcm_token=fcm_token, 
                user_id=current_user.id, 
                android_id=android_id
            )
            session.add(device)
            logging.info(f"[API] Registered new device (Android ID: {android_id}) for user {current_user.id}")
    
    else:
        device = session.query(Device).filter_by(fcm_token=fcm_token).first()
        
        if device:
            if device.user_id != current_user.id:
                device.user_id = current_user.id
                logging.info(f"[API] Re-assigned existing device token (legacy) to user {current_user.id}")
            else:
                logging.info(f"[API] Refreshed device token (legacy) for user {current_user.id}")
        else:
            device = Device(fcm_token=fcm_token, user_id=current_user.id)
            session.add(device)
            logging.info(f"[API] Registered new device (legacy) for user {current_user.id}")

    session.commit()
    return jsonify({'message': 'Device registered successfully'}), 201

# =============================================================================
# ROOM MANAGEMENT
# =============================================================================

@bp.route('/rooms', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_rooms(current_user):
    """
    Gets the list of rooms the current user is subscribed to.
    Filters out 'PENDING_DISCOVERY' rooms.
    Supports filtering by archive status via '?archived=true|false'.
    """
    # Parse the 'archived' query param (Default to False -> Show Active Rooms)
    show_archived_str = request.args.get('archived', 'false')
    show_archived = show_archived_str.lower() in ['true', '1', 't', 'yes']

    session = Session()
    
    subscriptions = session.query(UserRoomSubscription).join(TrackedRoom).filter(
        UserRoomSubscription.user_id == current_user.id,
        UserRoomSubscription.is_archived == show_archived, 
        ~TrackedRoom.room_id.startswith("PENDING_DISCOVERY") 
    ).all()
    
    rooms_list = []
    for sub in subscriptions:
        room = sub.room
        
        if room.room_id.startswith("PENDING_DISCOVERY"):
            continue

        tracked_count = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id, 
            room_id=room.id
        ).count()
        
        status = 'active'
        if room.is_complete:
            status = 'completed'
        elif room.is_suspended:
            if room.failed_poll_count >= 60:
                status = 'suspended_error'
            else:
                status = 'suspended_stale'

        rooms_list.append({
            'id': room.id,
            'room_id': room.room_id,
            'alias': sub.alias,
            'icon_name': sub.icon_name,
            'is_archived': sub.is_archived,
            'host': room.cached_full_address, 
            'is_complete': room.is_complete,
            'is_suspended': room.is_suspended,
            'status': status,  
            'total_slots_count': room.cached_total_slots,
            'tracked_slots_count': tracked_count
        })

    return jsonify(rooms_list)

@bp.route('/games', methods=['GET'])
@log_api_call
def get_games():
    """
    Returns a list of all unique game names known to the tracker
    (queried from the DatapackageCache).
    """
    session = Session()
    try:
        # Fetch distinct game names, ordered alphabetically
        games = session.query(DatapackageCache.game).distinct().order_by(DatapackageCache.game).all()
        game_list = [g[0] for g in games if g[0]]
        
        return jsonify(game_list)
    finally:
        Session.remove()

@bp.route('/rooms', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def add_room(current_user):
    """
    Adds a new room to the global tracking list and subscribes the
    current user to it.
    """
    data = request.json or {}
    room_url = data.get('room_url', '').strip()
    alias = data.get('alias', '').strip()
    icon_name = data.get('icon_name')

    if not room_url or len(room_url) > 512:
        return jsonify({'error': 'Invalid or missing room_url.'}), 400
    if not alias or len(alias) > 128:
        return jsonify({'error': 'Invalid or missing alias.'}), 400

    try:
        parsed_url = urlparse(room_url)
        hostname = parsed_url.hostname
        room_id = parsed_url.path.split('/')[-1] # This is the ap_room_id
    except Exception as e:
        return jsonify({'error': f'Invalid room_url: {e}'}), 400

    if not hostname or not room_id:
        return jsonify({'error': 'Could not parse hostname or room_id from URL'}), 400

    try:
        parsed_ip = ip_address(hostname)
        logging.warning(f"[API_WARN] User {current_user.id} tried to add a room using an IP address: {hostname}")
        return jsonify({'error': 'Adding rooms by IP address is not permitted.'}), 403
    except ValueError:
        pass # It's not an IP, so it's a valid hostname

    ALLOWED_HOSTNAMES = current_app.config.get('ALLOWED_HOSTNAMES', [])
    if hostname not in ALLOWED_HOSTNAMES:
        logging.warning(f"[API_WARN] User {current_user.id} tried to add a room with a disallowed hostname: {hostname}")
        return jsonify({'error': f"Hostname '{hostname}' is not in the list of allowed servers."}), 403

    session = Session()
    room = session.query(TrackedRoom).filter_by(room_id=room_id).first()

    ap_tracker_id = None # We'll store the tracker ID here

    if not room:
        logging.info(f"[API] First time seeing room {room_id}. Creating global record.")
        try:
            status_url = f"https://{hostname}/api/room_status/{room_id}"
            response = requests.get(status_url, timeout=10)
            response.raise_for_status()
            status_data = response.json()
            if not isinstance(status_data, dict):
                raise ValueError("Unexpected response format from room status API.")
            port = status_data.get('last_port', '')
            
            ap_tracker_id = status_data.get('tracker')
            
            players_raw = status_data.get('players', [])
            player_list = [{'slot_id': i + 1, 'name': p[0], 'game': p[1]} for i, p in enumerate(players_raw)]
            players_json = json.dumps(player_list)
            total_slots = len(player_list)

            room = TrackedRoom(
                room_id=room_id,
                hostname=hostname,
                cached_full_address=f"{hostname}:{port}",
                cached_players_json=players_json,
                cached_total_slots=total_slots,
                tracker_id=ap_tracker_id
            )
            session.add(room)
            session.flush()
        
        except requests.exceptions.RequestException as e:
            logging.error(f"[API_ERROR] Failed to fetch initial room status for {room_id}: {e}")
            return jsonify({'error': 'Could not connect to the room to verify its status.'}), 404
        except Exception as e:
            session.rollback()
            logging.error(f"[API_ERROR] Failed to process room status for {room_id}: {e}", exc_info=True)
            return jsonify({'error': 'An internal server error occurred.'}), 500
    
    else:
        ap_tracker_id = room.tracker_id
        if room.is_suspended:
            logging.info(f"[API] Reviving suspended room {room.id} because User {current_user.id} requested it.")
            room.is_suspended = False
            room.failed_poll_count = 0

    subscription = session.query(UserRoomSubscription).filter_by(
        user_id=current_user.id,
        room_id=room.id
    ).first()

    if subscription:
        return jsonify({'error': 'User is already subscribed to this room'}), 409
    subscription = UserRoomSubscription(
        user_id=current_user.id,
        room_id=room.id,
        alias=alias,
        icon_name=icon_name or 'person'
    )
    session.add(subscription)
    
    room.is_suspended = cast(bool, False)

    logging.info(f"[API] User {current_user.id} subscribed to room {room.id} ('{alias}')")

    session.commit()


    if current_user.cheese_api_key and ap_tracker_id and not current_user.is_guest:
        try:
            from .api_cheese import push_new_room_to_cheese
            import threading
            
            tracker_url = f"https://{hostname}/tracker/{ap_tracker_id}"
            app_context = current_app._get_current_object()
            
            threading.Thread(target=push_new_room_to_cheese, args=(
                app_context,
                current_user.id, 
                tracker_url,  
                room.room_id, 
                room_url,   
                alias         
            )).start()
        except Exception as e:
            logging.error(f"[API_ERROR] Failed to start Cheese new room thread: {e}", exc_info=True)

    return jsonify({'message': f"Now tracking room '{alias}'."}), 201


@bp.route('/rooms/<int:room_db_id>', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_subscription(current_user, room_db_id):
    """
    Updates a user's subscription details for a room (alias, icon, archive status).
    """
    data = request.json
    alias = data.get('alias')
    icon_name = data.get('icon_name')
    is_archived = data.get('is_archived') 

    # Allow update if ANY of these fields are present
    if alias is None and icon_name is None and is_archived is None:
        return jsonify({'error': 'No valid fields provided for update'}), 400

    session = Session()
    subscription = session.query(UserRoomSubscription).filter_by(
        user_id=current_user.id,
        room_id=room_db_id
    ).first()

    if not subscription:
        return jsonify({'error': 'Not subscribed to this room'}), 403

    if alias is not None:
        subscription.alias = alias
    if icon_name is not None:
        subscription.icon_name = icon_name
    if is_archived is not None:
        subscription.is_archived = bool(is_archived)

    session.commit()
    return jsonify({
        'message': 'Subscription updated.',
        'is_archived': subscription.is_archived
    })


@bp.route('/rooms/<int:room_db_id>', methods=['DELETE'])
@handle_db_errors
@log_api_call
@token_required
def unsubscribe_from_room(current_user, room_db_id):
    """
    Unsubscribes the current user from a room.
    This also deletes their tracked slots for that room.
    """
    session = Session()
    subscription = session.query(UserRoomSubscription).filter_by(
        user_id=current_user.id,
        room_id=room_db_id
    ).first()

    if not subscription:
        return jsonify({'error': 'Not subscribed to this room'}), 404

    # --- CHEESE INTEGRATION START ---
    # Capture details before deletion
    cheese_tracker_id = None
    if subscription.room:
        cheese_tracker_id = subscription.room.cheese_tracker_id

    session.delete(subscription)
    session.commit()
    
    logging.info(f"[API] User {current_user.id} unsubscribed from room {room_db_id}")

    # --- CHEESE INTEGRATION TRIGGER ---
    # If connected to Cheese, hide this tracker so it doesn't auto-reappear on next sync.
    if current_user.cheese_api_key and cheese_tracker_id:
        try:
            from .api_cheese import update_tracker_visibility
            import threading
            
            app_context = current_app._get_current_object()
            threading.Thread(
                target=update_tracker_visibility,
                args=(app_context, current_user.id, cheese_tracker_id, False) # False = Hide
            ).start()
        except Exception as e:
            logging.error(f"[API_ERROR] Failed to start Cheese visibility thread: {e}", exc_info=True)

    return jsonify({'message': 'Successfully unsubscribed from room.'})

# =============================================================================
# SLOT & PLAYER MANAGEMENT
# =============================================================================

@bp.route('/rooms/<int:room_db_id>/players', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_room_players(current_user, room_db_id):
    """
    Returns a list of all players in a room, indicating which are tracked
    by the current user and their notification preferences.
    """
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
        if not room:
            return jsonify({'error': 'Room not found'}), 404

        try:
            players_list = json.loads(room.cached_players_json or '[]')
            if not isinstance(players_list, list):
                players_list = []
        except (json.JSONDecodeError, TypeError):
            players_list = []

        tracked_slots_query = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id,
            room_id=room_db_id
        ).all()
        
        tracked_slots_map = {ts.slot_id: ts for ts in tracked_slots_query}

        response_players = []
        for p in players_list:
            slot_id = p.get('slot_id')
            tracked_slot_entry = tracked_slots_map.get(slot_id)

            response_players.append({
                'slot_id': slot_id,
                'name': p.get('name'),
                'alias': p.get('alias'),
                'game': p.get('game'),
                'is_finished': p.get('is_finished', False),
                'is_tracked': tracked_slot_entry is not None,
                'notify_progression': tracked_slot_entry.notify_progression if tracked_slot_entry else None,
                'notify_useful': tracked_slot_entry.notify_useful if tracked_slot_entry else None,
                'notify_hints': tracked_slot_entry.notify_hints if tracked_slot_entry else None
            })
        
        return jsonify(response_players)
    finally:
        Session.remove()


@bp.route('/rooms/<int:room_db_id>/slots', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_tracked_slots(current_user, room_db_id):
    """
    Updates the list of slots the current user is tracking for a specific room.
    The poller is now responsible for back-filling history.
    """
    data = request.json
    if 'tracked_slot_ids' not in data or not isinstance(data['tracked_slot_ids'], list):
        return jsonify({'error': 'Missing or invalid tracked_slot_ids'}), 400

    session = Session()
    subscription = session.query(UserRoomSubscription).filter_by(
        user_id=current_user.id,
        room_id=room_db_id
    ).first()
    if not subscription:
        return jsonify({'error': 'You are not subscribed to this room'}), 403

    room = subscription.room
    requested_ids = set(data.get('tracked_slot_ids', []))

    current_slots_query = session.query(UserTrackedSlot.slot_id).filter_by(user_id=current_user.id, room_id=room_db_id)
    current_tracked_ids = {slot.slot_id for slot in current_slots_query.all()}
    
    slots_to_add = requested_ids - current_tracked_ids
    slots_to_remove = current_tracked_ids - requested_ids

    if slots_to_remove:
        session.query(UserTrackedSlot).filter(
            UserTrackedSlot.user_id == current_user.id,
            UserTrackedSlot.room_id == room_db_id,
            UserTrackedSlot.slot_id.in_(slots_to_remove)
        ).delete(synchronize_session=False)
        logging.info(f"[API] User {current_user.id} untracked {len(slots_to_remove)} slots in room {room_db_id}.")

    if slots_to_add:
        objects_to_add = [
            UserTrackedSlot(
                user_id=current_user.id, 
                room_id=room_db_id, 
                slot_id=slot_id
            )
            for slot_id in slots_to_add if isinstance(slot_id, int) and slot_id > 0
        ]
        session.bulk_save_objects(objects_to_add)
        logging.info(f"[API] User {current_user.id} tracked {len(objects_to_add)} new slots in room {room_db_id}.")

    session.commit()

    # Hook for Cheese Tracker Integration
    # We do this AFTER commit so the local app state is saved even if Cheese API fails.
    # Ideally, for performance, you would offload this to a background task (like Celery or just a Thread),
    # but for V1, calling it directly here is acceptable if the number of slots changing is small.
    if current_user.cheese_api_key and (slots_to_add or slots_to_remove):
        try:
            # Assuming you might want to thread this to avoid blocking the response:
            # import threading
            # threading.Thread(target=push_slot_changes_to_cheese, args=(Session(), current_user, room_db_id, slots_to_add, slots_to_remove)).start()
            
            # Or just call it synchronously for now to test:
            # Note: We pass a NEW session to the helper if it's threaded, or reuse current if sync.
            # If using sync, just pass 'session' you already have open (but it's committed, so it's fine).
            from .api_cheese import push_slot_changes_to_cheese
            app_context = current_app._get_current_object()
            push_slot_changes_to_cheese(
                app_context, 
                current_user.id,  # Pass user_id
                room_db_id, 
                slots_to_add, 
                slots_to_remove
            )
        except Exception as e:
            logging.error(f"[API_ERROR] Failed to trigger Cheese push: {e}", exc_info=True)
            # Do not return an error to the user, standard sync succeeded.

    return jsonify({'message': 'Tracked slots updated.'})

# =============================================================================
# HISTORY ENDPOINTS
# =============================================================================

@bp.route('/rooms/<int:room_db_id>/history/items', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_item_history(current_user, room_db_id):
    """
    Gets the item history for a specific room, filtered for the slots the
    current user is tracking. Returns rich metadata including sender info
    and location names.
    """
    session = Session()
    room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
    if not room:
        return jsonify({'error': 'Room not found'}), 404

    # 1. Identify which slots this user is tracking in this room
    user_tracked_slots = session.query(UserTrackedSlot.slot_id).filter_by(
        user_id=current_user.id,
        room_id=room.id
    ).all()
    tracked_slot_ids = {slot[0] for slot in user_tracked_slots}

    if not tracked_slot_ids:
        return jsonify([]) 

    # 2. Query the history log for these slots
    query = session.query(NotifiedItem).filter(
        NotifiedItem.room_id == room.room_id,
        NotifiedItem.receiving_slot_id.in_(tracked_slot_ids)
    )

    since_timestamp = request.args.get('since')
    if since_timestamp:
        try:
            since_dt = datetime.fromisoformat(since_timestamp.replace('Z', '+00:00'))
            query = query.filter(NotifiedItem.timestamp > since_dt)
        except (ValueError, TypeError):
            pass 

    items = query.order_by(NotifiedItem.id.desc()).all()

    # 3. Load metadata (Players and Game Checksums)
    try:
        game_checksums = json.loads(room.game_checksums_json or '{}')
        if not isinstance(game_checksums, dict): game_checksums = {}

        players = json.loads(room.cached_players_json or '[]')
        if not isinstance(players, list): players = []
    except (json.JSONDecodeError, TypeError):
        logging.error(f"[API_ERROR] Room data for {room_db_id} is corrupt.", exc_info=True)
        return jsonify({'error': 'Room data is corrupt or missing.'}), 500
        
    player_map = {p['slot_id']: p for p in players}
    game_map = {p['slot_id']: p.get('game') for p in players} 

    history_pre_cache = []
    cache_keys_to_find = set()
    
    # 4. First Pass: Iterate items to gather info and identify missing names
    for item in items:
        receiver_id = item.receiving_slot_id
        sender_id = getattr(item, 'sending_slot_id', 0) 
        
        receiver_obj = player_map.get(receiver_id)
        sender_obj = player_map.get(sender_id)
        
        receiver_name = receiver_obj.get('name', f"Player {receiver_id}") if receiver_obj else f"Player {receiver_id}"
        sender_name = sender_obj.get('name', f"Player {sender_id}") if sender_obj else f"Player {sender_id}"
        
        receiver_game = game_map.get(receiver_id, "Unknown")
        sender_game = game_map.get(sender_id, "Unknown")
        
        is_finished = receiver_obj.get('is_finished', False) if receiver_obj else False
        
        # Determine Checksums for cache lookup
        rec_checksum = game_checksums.get(receiver_game)
        snd_checksum = game_checksums.get(sender_game)

        item_name_key = None
        location_name_key = None

        # A. Resolve Item Name (Uses Receiver's Game)
        if receiver_game and rec_checksum:
            item_name_key = (receiver_game, rec_checksum, 'item', item.item_id)
            cache_keys_to_find.add(item_name_key)
            
        # B. Resolve Location Name (Uses Sender's Game)
        if sender_game and snd_checksum:
            location_name_key = (sender_game, snd_checksum, 'location', item.location_id)
            cache_keys_to_find.add(location_name_key)

        receiver_name = receiver_obj.get('name', f"Player {receiver_id}") if receiver_obj else f"Player {receiver_id}"
        sender_name = sender_obj.get('name', f"Player {sender_id}") if sender_obj else f"Player {sender_id}"
        
        # Extract Aliases
        receiver_alias = receiver_obj.get('alias') if receiver_obj else None
        sender_alias = sender_obj.get('alias') if sender_obj else None

        history_pre_cache.append({
            "playerName": receiver_name,
            "playerAlias": receiver_alias,
            "receivingGame": receiver_game, 
            "senderName": sender_name,    
            "senderAlias": sender_alias,
            "senderGame": sender_game,   
            "timestamp": format_iso_z(item.timestamp),
            "tracker_id": room.tracker_id,
            "slot_id": receiver_id,
            "host": room.hostname,
            "isPlayerFinished": is_finished,
            "itemFlags": item.item_flags or 0,
            "_item_name_key": item_name_key,
            "_loc_name_key": location_name_key,
            "_raw_item_id": item.item_id,
            "_raw_loc_id": item.location_id
        })

    # 5. Bulk Fetch Names from Cache
    name_cache_map = {}
    if cache_keys_to_find:
        cache_query = session.query(
            DatapackageCache.game,
            DatapackageCache.checksum,
            DatapackageCache.entity_type,
            DatapackageCache.entity_id,
            DatapackageCache.entity_name
        ).filter(
            tuple_(
                DatapackageCache.game,
                DatapackageCache.checksum,
                DatapackageCache.entity_type,
                DatapackageCache.entity_id
            ).in_(cache_keys_to_find)
        )
        name_cache_map = {
            (c.game, c.checksum, c.entity_type, c.entity_id): c.entity_name
            for c in cache_query.all()
        }

    # 6. Second Pass: Build Final Response
    history = []
    for temp_item in history_pre_cache:
        item_name = name_cache_map.get(temp_item["_item_name_key"]) or f"Item ID {temp_item['_raw_item_id']}"
        location_name = name_cache_map.get(temp_item["_loc_name_key"]) or f"Location ID {temp_item['_raw_loc_id']}"
        
        history.append({
            "playerName": temp_item["playerName"],
            "playerAlias": temp_item["playerAlias"],
            "receivingGame": temp_item["receivingGame"], 
            "itemName": item_name,
            "senderName": temp_item["senderName"],       
            "senderAlias": temp_item["senderAlias"],
            "senderGame": temp_item["senderGame"],       
            "locationName": location_name,               
            "isPlayerFinished": temp_item["isPlayerFinished"],
            "itemFlags": temp_item["itemFlags"],
            "timestamp": temp_item["timestamp"],
            "tracker_id": temp_item["tracker_id"],
            "slot_id": temp_item["slot_id"],
            "host": temp_item["host"]
        })

    return jsonify(history)


@bp.route('/history/items', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_global_item_history(current_user):
    """
    Gets a global, aggregated item history feed for the current user.
    Refactored to use batch processing (yield_per) to prevent memory spikes.
    """
    session = Session()

    # 1. Get all (room_id, slot_id) tuples the user tracks.
    user_tracked_slots = session.query(UserTrackedSlot.room_id, UserTrackedSlot.slot_id).filter_by(
        user_id=current_user.id
    ).all()

    if not user_tracked_slots:
        return jsonify([])

    slots_by_room_db_id = {}
    for room_db_id, slot_id in user_tracked_slots:
        if room_db_id not in slots_by_room_db_id:
            slots_by_room_db_id[room_db_id] = set()
        slots_by_room_db_id[room_db_id].add(slot_id)

    # 2. Get a map of {room_db_id: room_uuid} and Pre-fetch Room Data.
    relevant_room_db_ids = list(slots_by_room_db_id.keys())
    
    room_objects = session.query(TrackedRoom).filter(TrackedRoom.id.in_(relevant_room_db_ids)).all()
    all_room_data = {r.room_id: r for r in room_objects}
    
    # We also need the user's subscriptions for Aliases/Icons
    subs_query = session.query(UserRoomSubscription).filter(
        UserRoomSubscription.user_id == current_user.id,
        UserRoomSubscription.room_id.in_(relevant_room_db_ids)
    )
    subs_map = {sub.room_id: sub for sub in subs_query.all()}

    # Map DB ID -> UUID for query construction
    room_db_to_uuid = {r.id: r.room_id for r in room_objects}

    filters = []
    for room_db_id, slot_ids in slots_by_room_db_id.items():
        room_uuid = room_db_to_uuid.get(room_db_id)
        if room_uuid:
            filters.append(
                (NotifiedItem.room_id == room_uuid) &
                (NotifiedItem.receiving_slot_id.in_(slot_ids))
            )

    if not filters:
        return jsonify([])

    # 3. Build the Query
    query = session.query(NotifiedItem).filter(or_(*filters))

    since_timestamp = request.args.get('since')
    if since_timestamp:
        try:
            since_dt = datetime.fromisoformat(since_timestamp.replace('Z', '+00:00'))
            query = query.filter(NotifiedItem.timestamp > since_dt)
        except (ValueError, TypeError):
            pass

    # Order by DESC so the client gets the newest timestamp for next sync
    query = query.order_by(NotifiedItem.id.desc())

    # 4. Batch Process the Results
    final_history_dicts = []
    BATCH_SIZE = 1000

    for batch_items in chunked_iterable(query.yield_per(BATCH_SIZE), BATCH_SIZE):
        
        history_pre_cache = []
        cache_keys_to_find = set()

        # Process this batch
        for item in batch_items:
            room_data = all_room_data.get(item.room_id)
            if not room_data:
                continue
            
            sub = subs_map.get(room_data.id)
            if not sub:
                continue
            
            try:
                players = json.loads(room_data.cached_players_json or '[]')
                if not isinstance(players, list): players = []

                game_checksums = json.loads(room_data.game_checksums_json or '{}')
                if not isinstance(game_checksums, dict): game_checksums = {}
            except (json.JSONDecodeError, TypeError):
                continue

            player_map = {p['slot_id']: p for p in players}
            game_map = {p['slot_id']: p.get('game') for p in players}
            
            receiver_id = item.receiving_slot_id
            sender_id = getattr(item, 'sending_slot_id', 0)

            receiver_obj = player_map.get(receiver_id)
            sender_obj = player_map.get(sender_id)
            
            receiver_name = receiver_obj.get('name', f"Player {receiver_id}") if receiver_obj else f"Player {receiver_id}"
            receiver_alias = receiver_obj.get('alias') if receiver_obj else None
            
            sender_name = sender_obj.get('name', f"Player {sender_id}") if sender_obj else f"Player {sender_id}"
            sender_alias = sender_obj.get('alias') if sender_obj else None
            
            receiver_game = game_map.get(receiver_id, "Unknown")
            sender_game = game_map.get(sender_id, "Unknown")
            
            is_finished = receiver_obj.get('is_finished', False) if receiver_obj else False

            rec_checksum = game_checksums.get(receiver_game)
            snd_checksum = game_checksums.get(sender_game)

            item_name_key = None
            location_name_key = None

            if receiver_game and rec_checksum:
                item_name_key = (receiver_game, rec_checksum, 'item', item.item_id)
                cache_keys_to_find.add(item_name_key)

            if sender_game and snd_checksum:
                location_name_key = (sender_game, snd_checksum, 'location', item.location_id)
                cache_keys_to_find.add(location_name_key)

            history_pre_cache.append({
                "db_id": room_data.id, 
                "alias": sub.alias, 
                "icon_name": sub.icon_name,
                "playerName": receiver_name,
                "playerAlias": receiver_alias, 
                "receivingGame": receiver_game, 
                "senderName": sender_name,    
                "senderAlias": sender_alias,  
                "senderGame": sender_game,    
                "timestamp": format_iso_z(item.timestamp),
                "tracker_id": room_data.tracker_id,
                "slot_id": receiver_id,
                "host": room_data.hostname,
                "_item_name_key": item_name_key,
                "_loc_name_key": location_name_key,
                "_raw_item_id": item.item_id,
                "_raw_loc_id": item.location_id,
                "isPlayerFinished": is_finished,
                "itemFlags": item.item_flags or 0
            })

        # Bulk Fetch Names for THIS batch only
        name_cache_map = {}
        if cache_keys_to_find:
            cache_query = session.query(
                DatapackageCache.game,
                DatapackageCache.checksum,
                DatapackageCache.entity_type,
                DatapackageCache.entity_id,
                DatapackageCache.entity_name
            ).filter(
                tuple_(
                    DatapackageCache.game,
                    DatapackageCache.checksum,
                    DatapackageCache.entity_type,
                    DatapackageCache.entity_id
                ).in_(cache_keys_to_find)
            )

            name_cache_map = {
                (c.game, c.checksum, c.entity_type, c.entity_id): c.entity_name
                for c in cache_query.all()
            }

        # Build Final lightweight dicts
        for temp_item in history_pre_cache:
            item_name = name_cache_map.get(temp_item["_item_name_key"]) or f"Item ID {temp_item['_raw_item_id']}"
            location_name = name_cache_map.get(temp_item["_loc_name_key"]) or f"Location ID {temp_item['_raw_loc_id']}"

            final_history_dicts.append({
                "db_id": temp_item["db_id"], 
                "alias": temp_item["alias"], 
                "icon_name": temp_item["icon_name"],
                "playerName": temp_item['playerName'],
                "playerAlias": temp_item['playerAlias'],
                "receivingGame": temp_item['receivingGame'],
                "itemName": item_name,
                "senderName": temp_item['senderName'],     
                "senderAlias": temp_item['senderAlias'],
                "senderGame": temp_item['senderGame'],      
                "locationName": location_name,              
                "isPlayerFinished": temp_item['isPlayerFinished'],
                "itemFlags": temp_item['itemFlags'],
                "timestamp": temp_item["timestamp"],
                "tracker_id": temp_item["tracker_id"],
                "slot_id": temp_item["slot_id"],
                "host": temp_item["host"]
            })
        
        del history_pre_cache
        del cache_keys_to_find
        del name_cache_map
        del batch_items

    return jsonify(final_history_dicts)


# =============================================================================
# USER ENDPOINT
# =============================================================================

@bp.route('/users/me', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_current_user(current_user):
    """
    Returns the profile information for the currently authenticated user.
    Handles both guest and authenticated (Discord) users.
    """

    if current_user.is_guest:
        return jsonify({
            'discord_id': None,
            'discord_username': 'Guest',
            'avatar_url': None,
            'notify_progression_default': current_user.notify_progression_default,
            'notify_useful_default': current_user.notify_useful_default,
            'notify_hints_default': current_user.notify_hints_default,
            'notify_finished_default': current_user.notify_finished_default,
            'use_condensed_messages_default': current_user.use_condensed_messages_default,
            'notify_hints_remote_items_default': current_user.notify_hints_remote_items_default,
            'is_cheese_connected': current_user.cheese_api_key is not None,
            'ui_show_finished_default': current_user.ui_show_finished_default,
            'ui_show_found_hints_default': current_user.ui_show_found_hints_default,
            'is_guest': True
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
            'notify_hints_default': current_user.notify_hints_default,
            'notify_finished_default': current_user.notify_finished_default,
            'use_condensed_messages_default': current_user.use_condensed_messages_default,
            'notify_hints_remote_items_default': current_user.notify_hints_remote_items_default,
            'is_cheese_connected': current_user.cheese_api_key is not None,
            'ui_show_finished_default': current_user.ui_show_finished_default,
            'ui_show_found_hints_default': current_user.ui_show_found_hints_default,
            'is_guest': False
        })

@bp.route('/users/me/tracked-slots', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_user_tracked_slots(current_user):
    """
    Returns a list of all rooms and slots the authenticated user is tracking.
    Also filters out 'PENDING_DISCOVERY' rooms.
    """
    session = Session()
    try:
        subscriptions = session.query(UserRoomSubscription).join(TrackedRoom).filter(
            UserRoomSubscription.user_id == current_user.id,
            ~TrackedRoom.room_id.startswith("PENDING_DISCOVERY")
        ).options(
            selectinload(UserRoomSubscription.room),
            selectinload(UserRoomSubscription.tracked_slots)
        ).order_by(UserRoomSubscription.alias).all()

        response_data = []
        for sub in subscriptions:
            room_data = sub.room
            if not room_data: continue

            # --- FILTER: Hide Pending Discovery Rooms ---
            if room_data.room_id.startswith("PENDING_DISCOVERY"):
                continue
            # --------------------------------------------

            try:
                players_json = json.loads(room_data.cached_players_json or '[]')
                if not isinstance(players_json, list):
                    players_json = []
            except (json.JSONDecodeError, TypeError):
                players_json = []

            # --- Store full player object to access alias ---
            players_map = {p['slot_id']: p for p in players_json}

            tracked_slots_list = []
            for slot in sorted(sub.tracked_slots, key=lambda s: s.slot_id):
                # Resolve Name and Alias
                p_obj = players_map.get(slot.slot_id)
                p_name = p_obj.get('name', f"Player {slot.slot_id}") if p_obj else f"Player {slot.slot_id}"
                p_alias = p_obj.get('alias') if p_obj else None
                p_finished = p_obj.get('is_finished', False) if p_obj else False

                tracked_slots_list.append({
                    'slot_id': slot.slot_id,
                    'player_name': p_name,
                    'player_alias': p_alias,
                    'is_finished': p_finished,
                    'notify_progression': slot.notify_progression,
                    'notify_useful': slot.notify_useful,
                    'notify_hints': slot.notify_hints,
                    'notify_hints_remote_items': slot.notify_hints_remote_items,
                    'notify_finished': slot.notify_finished,
                    'use_condensed_messages': slot.use_condensed_messages 
                })

            response_data.append({
                'room_db_id': sub.room_id,
                'room_alias': sub.alias,
                'icon_name': sub.icon_name,
                'is_archived': sub.is_archived,
                'tracked_slots': tracked_slots_list
            })

        return jsonify(response_data)
    finally:
        Session.remove()

@bp.route('/users/me/preferences', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_user_preferences(current_user):
    """
    Updates the global notification preferences for the authenticated user.
    """
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

        session.commit()
        return jsonify({'message': 'Preferences updated successfully'}), 200
    except Exception as e:
        session.rollback()
        logging.error(f"Failed to update preferences for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'error': 'An internal server error occurred.'}), 500
    finally:
        Session.remove()


@bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/preferences', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_slot_preferences(current_user, room_db_id, slot_id):
    """
    Updates the per-slot notification preferences for the authenticated user.
    'None' (null) means "use global default".
    """
    data = request.json or {}
    session = Session()
    try:
        tracked_slot = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id,
            room_id=room_db_id,
            slot_id=slot_id
        ).first()

        if not tracked_slot:
            return jsonify({'error': 'Tracked slot not found'}), 404

        if 'notify_progression' in data:
            tracked_slot.notify_progression = data['notify_progression']
        if 'notify_useful' in data:
            tracked_slot.notify_useful = data['notify_useful']
        if 'notify_hints' in data:
            tracked_slot.notify_hints = data['notify_hints']
        if 'notify_hints_remote_items' in data:
            tracked_slot.notify_hints_remote_items = data['notify_hints_remote_items']
        if 'notify_finished' in data:
            tracked_slot.notify_finished = data['notify_finished']
        if 'use_condensed_messages' in data:
            tracked_slot.use_condensed_messages = data['use_condensed_messages']

        session.commit()
        return jsonify({'message': 'Slot preferences updated successfully'}), 200
    except Exception as e:
        session.rollback()
        logging.error(f"Failed to update slot preferences for user {current_user.id} (room {room_db_id}, slot {slot_id}): {e}", exc_info=True)
        return jsonify({'error': 'An internal server error occurred.'}), 500
    finally:
        Session.remove()


@bp.route('/users/me', methods=['DELETE'])
@handle_db_errors
@log_api_call
@token_required
def delete_current_user(current_user):
    """
    Deletes the currently authenticated user and all their associated data
    (devices, subscriptions, tracked slots) from the database.
    Also invalidates the token used to make the request.
    """
    session = Session()
    try:
        # 1. Invalidate the current token
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

        # 2. Delete the user record
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

# Helper function to process hints
def process_hints_for_user(session, user_id, room_db_id=None, since_timestamp=None, include_found=False):
    """Fetches and categorizes hints for a user, optionally filtered by room and timestamp."""

    # Get all slots tracked by the user (optionally filtered by room)
    tracked_slots_query = session.query(UserTrackedSlot.room_id, UserTrackedSlot.slot_id).filter_by(user_id=user_id)
    if room_db_id:
        tracked_slots_query = tracked_slots_query.filter_by(room_id=room_db_id)

    # Create a set of (room_db_id, slot_id) tuples for efficient lookup
    user_tracked_tuples = {(ts.room_id, ts.slot_id) for ts in tracked_slots_query.all()}
    if not user_tracked_tuples:
        return {"hints_for_you": [], "hints_by_you": []} # No slots tracked

    # Map room_db_id back to room_uuid for querying NotifiedHint
    room_map_query = session.query(TrackedRoom.id, TrackedRoom.room_id)
    if room_db_id:
         room_map_query = room_map_query.filter_by(id=room_db_id)
    else:
        # Filter rooms where the user is tracking at least one slot
        room_db_ids_tracked = {room_id for room_id, slot_id in user_tracked_tuples}
        room_map_query = room_map_query.filter(TrackedRoom.id.in_(room_db_ids_tracked))

    room_id_to_uuid = {db_id: uuid for db_id, uuid in room_map_query.all()}
    relevant_room_uuids = list(room_id_to_uuid.values())

    if not relevant_room_uuids:
         return {"hints_for_you": [], "hints_by_you": []}

    hints_query = session.query(NotifiedHint).filter(
        NotifiedHint.room_id.in_(relevant_room_uuids)
    )

    if not include_found:
        hints_query = hints_query.filter(NotifiedHint.is_found == False)

    hints_query = hints_query.order_by(desc(NotifiedHint.id))


    if since_timestamp:
        try:
            since_dt = datetime.fromisoformat(since_timestamp.replace('Z', '+00:00'))
            if hasattr(NotifiedHint, 'timestamp'):
                 hints_query = hints_query.filter(NotifiedHint.timestamp > since_dt)
            else:
                 logging.warning(f"[HINT_API_WARN] 'since' parameter provided but NotifiedHint has no timestamp column.")

        except ValueError:
            logging.warning(f"[HINT_API_WARN] Invalid 'since' timestamp format: {since_timestamp}")


    all_relevant_hints = hints_query.all()

    hints_for_you = []
    hints_by_you = []

    # Get room/player/game info needed for names
    all_room_db_ids = list(room_id_to_uuid.keys())
    all_subs = session.query(UserRoomSubscription).filter(UserRoomSubscription.room_id.in_(all_room_db_ids)).all()
    alias_map = {sub.room_id: sub.alias for sub in all_subs} # room_db_id -> alias

    all_rooms_full = session.query(TrackedRoom).filter(TrackedRoom.id.in_(all_room_db_ids)).all()
    
    player_map_by_room = {}
    game_map_by_room = {}
    checksum_map_by_room = {}

    for r in all_rooms_full:
        try:
            players_json = json.loads(r.cached_players_json or '[]')
            if not isinstance(players_json, list): raise ValueError()
        except (json.JSONDecodeError, ValueError):
            players_json = []

        try:
            checksum_json = json.loads(r.game_checksums_json or '{}')
            if not isinstance(checksum_json, dict): raise ValueError()
        except (json.JSONDecodeError, ValueError):
            checksum_json = {}

        player_map_by_room[r.id] = {p['slot_id']: p for p in players_json}
        game_map_by_room[r.id] = {p['slot_id']: p.get('game') for p in players_json}
        checksum_map_by_room[r.id] = checksum_json
    uuid_to_db_id = {v: k for k, v in room_id_to_uuid.items()}


    # 1. Gather all name keys we need to look up
    cache_keys_to_find = set()
    temp_hint_data = [] # Store processed hints temporarily

    for hint in all_relevant_hints:
        room_db_id_for_hint = uuid_to_db_id.get(hint.room_id)
        if not room_db_id_for_hint: continue 

        is_item_owner_tracked = (room_db_id_for_hint, hint.item_owner_id) in user_tracked_tuples
        is_location_owner_tracked = (room_db_id_for_hint, hint.location_owner_id) in user_tracked_tuples

        if not (is_item_owner_tracked or is_location_owner_tracked):
            continue 

        player_map = player_map_by_room.get(room_db_id_for_hint, {})
        game_map = game_map_by_room.get(room_db_id_for_hint, {})
        checksum_map = checksum_map_by_room.get(room_db_id_for_hint, {})

        io_obj = player_map.get(hint.item_owner_id)
        item_owner_name = io_obj.get('name', f"Player {hint.item_owner_id}") if io_obj else f"Player {hint.item_owner_id}"
        lo_obj = player_map.get(hint.location_owner_id)
        location_owner_name = lo_obj.get('name', f"Player {hint.location_owner_id}") if lo_obj else f"Player {hint.location_owner_id}"
        
        item_owner_game = game_map.get(hint.item_owner_id)
        location_owner_game = game_map.get(hint.location_owner_id)

        item_checksum = checksum_map.get(item_owner_game) if item_owner_game else None
        location_checksum = checksum_map.get(location_owner_game) if location_owner_game else None

        item_name_key = None
        location_name_key = None

        if item_owner_game and item_checksum:
            item_name_key = (item_owner_game, item_checksum, 'item', hint.item_id)
            cache_keys_to_find.add(item_name_key)
            
        if location_owner_game and location_checksum:
            location_name_key = (location_owner_game, location_checksum, 'location', hint.location_id)
            cache_keys_to_find.add(location_name_key)

        temp_hint_data.append({
            "hint_obj": hint,
            "room_db_id": room_db_id_for_hint,
            "is_item_owner_tracked": is_item_owner_tracked,
            "item_owner_name": item_owner_name,
            "location_owner_name": location_owner_name,
            "item_name_key": item_name_key,
            "location_name_key": location_name_key
        })

    name_cache_map = {}
    if cache_keys_to_find:
        cache_query = session.query(
            DatapackageCache.game,
            DatapackageCache.checksum,
            DatapackageCache.entity_type,
            DatapackageCache.entity_id,
            DatapackageCache.entity_name
        ).filter(
            tuple_(
                DatapackageCache.game,
                DatapackageCache.checksum,
                DatapackageCache.entity_type,
                DatapackageCache.entity_id
            ).in_(cache_keys_to_find)
        )
        name_cache_map = {
            (c.game, c.checksum, c.entity_type, c.entity_id): c.entity_name
            for c in cache_query.all()
        }

    for temp_data in temp_hint_data:
        hint = temp_data["hint_obj"]
        
        item_name = name_cache_map.get(temp_data["item_name_key"]) or f"Item ID {hint.item_id}"
        location_name = name_cache_map.get(temp_data["location_name_key"]) or f"Location ID {hint.location_id}"
        io_obj = player_map.get(hint.item_owner_id)
        lo_obj = player_map.get(hint.location_owner_id)

        # EXTRACT 'name' STRING EXPLICITLY
        item_owner_name = io_obj.get('name', f"Player {hint.item_owner_id}") if io_obj else f"Player {hint.item_owner_id}"
        item_owner_alias = io_obj.get('alias') if io_obj else None

        location_owner_name = lo_obj.get('name', f"Player {hint.location_owner_id}") if lo_obj else f"Player {hint.location_owner_id}"
        location_owner_alias = lo_obj.get('alias') if lo_obj else None

        ts_val = None
        if hasattr(hint, 'timestamp') and hint.timestamp:
            ts_val = format_iso_z(hint.timestamp)
        else:
            ts_val = format_iso_z(datetime.fromtimestamp(hint.id / 1000.0, tz=timezone.utc))

        hint_data = {
            "id": hint.id,
            "room_db_id": temp_data["room_db_id"],
            "room_alias": alias_map.get(temp_data["room_db_id"], "Unknown Room"),
            "item_owner_id": hint.item_owner_id,
            "item_owner_name": temp_data["item_owner_name"],
            "item_owner_alias": item_owner_alias, 
            "location_owner_id": hint.location_owner_id,
            "location_owner_name": temp_data["location_owner_name"],
            "location_owner_alias": location_owner_alias,
            "item_name": item_name,
            "location_name": location_name,
            "is_found": getattr(hint, 'is_found', False),
            "timestamp": ts_val,
            "item_flags": getattr(hint, 'item_flags', 0)
        }
        
        if temp_data["is_item_owner_tracked"]:
            hints_for_you.append(hint_data)
        else:
            hints_by_you.append(hint_data)

    hints_for_you.sort(key=lambda h: h.get('timestamp', '0'), reverse=True)
    hints_by_you.sort(key=lambda h: h.get('timestamp', '0'), reverse=True)

    return {"hints_for_you": hints_for_you, "hints_by_you": hints_by_you}


@bp.route('/history/hints', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_global_hint_history(current_user):
    """Returns categorized global hint history for the authenticated user."""
    since = request.args.get('since')
    
    include_found_str = request.args.get('include_found', 'false')
    include_found = include_found_str.lower() in ['true', '1', 't', 'yes']
    
    session = Session()
    try:
        result = process_hints_for_user(
            session, 
            current_user.id, 
            since_timestamp=since,
            include_found=include_found
        )
        return jsonify(result)
    finally:
        Session.remove()


@bp.route('/rooms/<int:room_db_id>/history/hints', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_room_hint_history(current_user, room_db_id):
    """Returns categorized hint history for a specific room for the authenticated user."""
    since = request.args.get('since')
    
    include_found_str = request.args.get('include_found', 'false')
    include_found = include_found_str.lower() in ['true', '1', 't', 'yes']
    
    session = Session()
    try:
        sub_exists = session.query(UserRoomSubscription.user_id).filter_by(
            user_id=current_user.id, room_id=room_db_id
        ).limit(1).scalar() is not None
        if not sub_exists:
            return jsonify({'error': 'Subscription not found'}), 404

        result = process_hints_for_user(
            session, 
            current_user.id, 
            room_db_id=room_db_id, 
            since_timestamp=since,
            include_found=include_found
        )
        return jsonify(result)
    finally:
        Session.remove()

@bp.route('/devices', methods=['DELETE'])
@handle_db_errors
@log_api_call
@token_required
def unregister_device(current_user):
    """
    Deletes a specific device (identified by its FCM token)
    from the user's account to stop notifications.
    """
    data = request.json
    fcm_token = data.get('fcm_token')

    if not fcm_token:
        return jsonify({'error': 'Missing fcm_token'}), 400

    session = Session()
    try:
        # Find the specific device for this user
        device = session.query(Device).filter_by(
            user_id=current_user.id,
            fcm_token=fcm_token
        ).first()

        if not device:
            # This is not really an error, the device just isn't registered.
            logging.info(f"[API] Device {fcm_token} not found for user {current_user.id}, cannot unregister.")
            return jsonify({'message': 'Device not found'}), 404

        # Delete the device
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

MAX_IGNORE_ITEMS = 100

@bp.route('/users/me/ignore-list', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_ignore_list(current_user):
    """
    Returns the user's list of ignored items.
    """
    session = Session()
    try:
        ignore_items = session.query(UserIgnoreItem).filter_by(user_id=current_user.id).all()
        
        items = []
        for item in ignore_items:
            items.append({
                'id': item.id,
                'item_name': item.item_name,
                'game_name': item.game_name,
                'created_at': item.created_at.isoformat()
            })
        return jsonify(items)
    finally:
        Session.remove()

@bp.route('/users/me/ignore-list', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def add_ignore_item(current_user):
    """
    Adds a new item to the ignore list.
    payload: { "item_name": "Power Star", "game_name": "Super Mario 64" (optional) }
    """
    data = request.json
    item_name = data.get('item_name', '').strip()
    game_name = data.get('game_name')
    
    if game_name:
        game_name = game_name.strip()

    if not item_name:
        return jsonify({'error': 'item_name is required'}), 400

    session = Session()
    try:
        # SECURITY: Prevent list bloating
        count = session.query(UserIgnoreItem).filter_by(user_id=current_user.id).count()
        if count >= MAX_IGNORE_ITEMS:
            return jsonify({'error': f'Limit reached. You cannot have more than {MAX_IGNORE_ITEMS} ignored items.'}), 400

        # Check for duplicates (though DB constraint handles this, it's nicer to return 409 explicitly)
        existing = session.query(UserIgnoreItem).filter_by(
            user_id=current_user.id,
            item_name=item_name,
            game_name=game_name
        ).first()

        if existing:
            return jsonify({'error': 'This item is already in your ignore list.'}), 409

        new_item = UserIgnoreItem(
            user_id=current_user.id,
            item_name=item_name,
            game_name=game_name
        )
        session.add(new_item)
        session.commit()
        
        logging.info(f"[API] User {current_user.id} ignored '{item_name}' (Game: {game_name or 'Global'})")
        
        return jsonify({
            'message': 'Item added to ignore list.',
            'id': new_item.id
        }), 201
    except Exception as e:
        session.rollback()
        raise e
    finally:
        Session.remove()

@bp.route('/users/me/ignore-list/<int:item_id>', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_ignore_item(current_user, item_id):
    """
    Updates an existing ignore rule (e.g. fixing a typo or changing the game).
    """
    data = request.json
    new_item_name = data.get('item_name', '').strip()
    
    # game_name can be None (Global) or a string
    new_game_name = data.get('game_name')
    if new_game_name:
        new_game_name = new_game_name.strip()

    if not new_item_name:
        return jsonify({'error': 'item_name is required'}), 400

    session = Session()
    try:
        # Find the rule
        item = session.query(UserIgnoreItem).filter_by(id=item_id, user_id=current_user.id).first()
        if not item:
            return jsonify({'error': 'Rule not found'}), 404

        # Check for duplicates (excluding the current item itself)
        existing = session.query(UserIgnoreItem).filter(
            UserIgnoreItem.user_id == current_user.id,
            UserIgnoreItem.item_name == new_item_name,
            UserIgnoreItem.game_name == new_game_name,
            UserIgnoreItem.id != item_id 
        ).first()

        if existing:
            return jsonify({'error': 'A rule for this item/game already exists.'}), 409

        # Apply updates
        item.item_name = new_item_name
        item.game_name = new_game_name
        
        session.commit()
        return jsonify({'message': 'Rule updated.'})
    finally:
        Session.remove()

@bp.route('/users/me/ignore-list/<int:item_id>', methods=['DELETE'])
@handle_db_errors
@log_api_call
@token_required
def remove_ignore_item(current_user, item_id):
    """
    Removes an item from the ignore list by ID.
    """
    session = Session()
    try:
        item = session.query(UserIgnoreItem).filter_by(
            id=item_id, 
            user_id=current_user.id
        ).first()

        if not item:
            return jsonify({'error': 'Item not found'}), 404

        session.delete(item)
        session.commit()
        
        logging.info(f"[API] User {current_user.id} removed ignore rule {item_id}")
        return jsonify({'message': 'Item removed from ignore list.'})
    except Exception as e:
        session.rollback()
        raise e
    finally:
        Session.remove()