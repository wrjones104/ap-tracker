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
from sqlalchemy import or_, desc, tuple_, func
from firebase_admin import messaging

from . import Session, get_firebase_app
from .utils import verify_ap_server
from .models import (
    User, Device, TrackedRoom, UserRoomSubscription, UserTrackedSlot, 
    DatapackageCache, NotifiedItem, NotifiedHint, JWTBlocklist, UserIgnoreItem,
    SlotItemThreshold, SlotItemCount
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
            
            current_user.last_activity = datetime.utcnow()
            session.commit() 
            
            # 1. Refresh: Reloads the attributes (like 'id') from DB so they aren't "expired"
            session.refresh(current_user)
            # 2. Expunge: Detaches the object from this session so it can be used 
            #    safely in the next function (which has its own session).
            session.expunge(current_user)

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
    Ensures that the FCM token is unique to the current active user by 
    removing it from any other users (e.g., previous guest accounts).
    """
    data = request.json or {}
    fcm_token = data.get('fcm_token')
    android_id = data.get('android_id') 

    if not fcm_token:
        return jsonify({'error': 'Missing fcm_token'}), 400

    session = Session()

    # --- Prune Duplicate Tokens ---
    # If this FCM token exists for ANY user other than the current one, delete it.
    # This handles app reinstalls (new Guest ID) or account switching.
    stale_devices = session.query(Device).filter(
        Device.fcm_token == fcm_token,
        Device.user_id != current_user.id
    ).all()

    if stale_devices:
        for stale in stale_devices:
            logging.info(f"[API] Unlinking FCM token from old User {stale.user_id} to assign to Current User {current_user.id}")
            session.delete(stale)
    # --------------------------------------------------

    device = None

    if android_id:
        # Modern App Logic (Version 9+)
        # We look for a device record belonging to THIS user with THIS android_id
        device = session.query(Device).filter_by(
            user_id=current_user.id,
            android_id=android_id
        ).first()

        if device:
            # Update existing record for this user
            if device.fcm_token != fcm_token:
                device.fcm_token = fcm_token
                logging.info(f"[API] Refreshed FCM token for existing device (Android ID: {android_id}) for user {current_user.id}")
        else:
            # Create new record
            device = Device(
                fcm_token=fcm_token, 
                user_id=current_user.id, 
                android_id=android_id
            )
            session.add(device)
            logging.info(f"[API] Registered new device (Android ID: {android_id}) for user {current_user.id}")
    
    else:
        # Legacy Logic (< Version 9)
        # We look for a device by token belonging to THIS user (since we pruned others above)
        device = session.query(Device).filter_by(fcm_token=fcm_token, user_id=current_user.id).first()
        
        if not device:
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

    has_explicit_scheme = room_url.startswith(('http://', 'https://'))

    if room_url and not has_explicit_scheme:
        first_part = room_url.split('/')[0].split(':')[0]
        is_local = False
        if os.environ.get('FLASK_ENV', 'production') == 'development':
            if first_part in ('localhost', '127.0.0.1', '10.0.2.2'):
                is_local = True
            else:
                import socket
                try:
                    resolved_ip = socket.gethostbyname(first_part)
                    from ipaddress import ip_address
                    ip = ip_address(resolved_ip)
                    if ip.is_private or ip.is_loopback:
                        is_local = True
                except Exception:
                    pass

                if not is_local:
                    if '.' not in first_part:
                        is_local = True
                    elif first_part.endswith(('.local', '.lan', '.internal', '.test', '.example')):
                        is_local = True

        if is_local:
            room_url = f"http://{room_url}"
        else:
            room_url = f"https://{room_url}"

    if not room_url or len(room_url) > 512:
        return jsonify({'error': 'Invalid or missing room_url.'}), 400
    if not alias or len(alias) > 128:
        return jsonify({'error': 'Invalid or missing alias.'}), 400

    try:
        parsed_url = urlparse(room_url)
        hostname = parsed_url.netloc or parsed_url.hostname
        room_id = parsed_url.path.strip('/').split('/')[-1] # This is the ap_room_id
    except Exception as e:
        return jsonify({'error': f'Invalid room_url: {e}'}), 400

    if not hostname or not room_id:
        return jsonify({'error': 'Could not parse hostname or room_id from URL'}), 400

    session = Session()
    room = session.query(TrackedRoom).filter_by(room_id=room_id).first()

    ap_tracker_id = None # We'll store the tracker ID here

    if not room:
        logging.info(f"[API] First time seeing room {room_id}. Creating global record.")
        try:
            # Verify the room uses the secure async handshake
            # asyncio.run blocks the worker, which is acceptable here as there's a 30s timeout.
            room_data = asyncio.run(verify_ap_server(hostname, room_id))
            
            ap_tracker_id = room_data['ap_tracker_id']

            room = TrackedRoom(
                room_id=room_data['room_id'],
                hostname=room_data['hostname'],
                cached_full_address=room_data['cached_full_address'],
                cached_players_json=room_data['cached_players_json'],
                cached_total_slots=room_data['cached_total_slots'],
                tracker_id=ap_tracker_id
            )
            session.add(room)
            session.flush()
        
        except ValueError as e:
            logging.warning(f"[API_WARN] User {current_user.id} failed to add room: {e}")
            return jsonify({'error': str(e)}), 400
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
            
            from .utils import get_web_base_url
            tracker_url = f"{get_web_base_url(hostname)}/tracker/{ap_tracker_id}"
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
            try:
                slot_id_int = int(slot_id) if slot_id is not None else None
            except (ValueError, TypeError):
                slot_id_int = None
            
            tracked_slot_entry = tracked_slots_map.get(slot_id_int) if slot_id_int is not None else None

            is_tracked = tracked_slot_entry is not None

            response_players.append({
                'slot_id': slot_id_int if slot_id_int is not None else slot_id,
                'name': p.get('name'),
                'alias': p.get('alias'),
                'game': p.get('game'),
                'is_finished': p.get('is_finished', False),
                'is_tracked': is_tracked,
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
    
    # Coerce slot IDs to integers safely to prevent type mismatches
    raw_requested_ids = data.get('tracked_slot_ids', [])
    requested_ids = set()
    for sid in raw_requested_ids:
        try:
            requested_ids.add(int(sid))
        except (ValueError, TypeError):
            pass

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
        # Explicitly pass added_at to bypass bulk_save_objects bypassing column default values
        objects_to_add = [
            UserTrackedSlot(
                user_id=current_user.id, 
                room_id=room_db_id, 
                slot_id=slot_id,
                added_at=datetime.utcnow()
            )
            for slot_id in slots_to_add if isinstance(slot_id, int) and slot_id > 0
        ]
        session.bulk_save_objects(objects_to_add)
        logging.info(f"[API] User {current_user.id} tracked {len(objects_to_add)} new slots in room {room_db_id}.")

    session.commit()

    # Hook for Cheese Tracker Integration
    # We do this AFTER commit so the local app state is saved even if Cheese API fails.
    # We offload this to a background thread to prevent blocking the response.
    if current_user.cheese_api_key and (slots_to_add or slots_to_remove):
        try:
            import threading
            from .api_cheese import push_slot_changes_to_cheese
            app_context = current_app._get_current_object()
            threading.Thread(target=push_slot_changes_to_cheese, args=(
                app_context, 
                current_user.id,
                room_db_id, 
                slots_to_add, 
                slots_to_remove
            )).start()
        except Exception as e:
            logging.error(f"[API_ERROR] Failed to trigger Cheese push thread: {e}", exc_info=True)
            # Do not return an error to the user, local state update succeeded.

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
    user_tracked_slots = session.query(UserTrackedSlot.slot_id, UserTrackedSlot.added_at).filter_by(
        user_id=current_user.id,
        room_id=room.id
    ).all()

    if not user_tracked_slots:
        return jsonify([]) 

    # 2. Query the history log for these slots
    since_timestamp = request.args.get('since')
    since_dt = None
    if since_timestamp:
        try:
            since_dt = datetime.fromisoformat(since_timestamp.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            pass 

    if since_dt:
        # Build slot-specific query filters in an `or_` clause
        slot_filters = []
        for slot_id, added_at in user_tracked_slots:
            added_at_utc = added_at.replace(tzinfo=timezone.utc) if added_at and added_at.tzinfo is None else added_at
            # If added_at is NULL (unknown) OR newer than since_dt, bypass the since filter
            # for a full backfill of this slot's history.
            if not added_at_utc or added_at_utc > since_dt:
                # Bypass `since` filter for this slot (sync backfill)
                slot_filters.append(NotifiedItem.receiving_slot_id == slot_id)
            else:
                # Normal filter with since_dt
                slot_filters.append(
                    (NotifiedItem.receiving_slot_id == slot_id) & (NotifiedItem.timestamp > since_dt)
                )
        query = session.query(NotifiedItem).filter(
            NotifiedItem.room_id == room.room_id,
            or_(*slot_filters)
        )
    else:
        tracked_slot_ids = {slot[0] for slot in user_tracked_slots}
        query = session.query(NotifiedItem).filter(
            NotifiedItem.room_id == room.room_id,
            NotifiedItem.receiving_slot_id.in_(tracked_slot_ids)
        )

    # Order by ID. Use ASC when 'since' is provided to allow sequential syncing; otherwise DESC for history.
    query = query.order_by(NotifiedItem.id.asc() if since_dt else NotifiedItem.id.desc())

    # --- Pagination ---
    try:
        limit = max(1, min(int(request.args.get('limit', 50)), 100))
        offset = max(int(request.args.get('offset', 0)), 0)
    except (ValueError, TypeError):
        limit = 50
        offset = 0
    
    query = query.limit(limit).offset(offset)

    items = query.all()

    # 3. Calculate counts for each unique item in this history set
    item_counts = {}
    if items:
        count_keys = set((item.room_id, item.receiving_slot_id, item.item_id) for item in items)
        # We query the NEW materialized table for the CURRENT total count of each (room, slot, item) triple
        counts_query = session.query(
            SlotItemCount.room_id, 
            SlotItemCount.slot_id, 
            SlotItemCount.item_id, 
            SlotItemCount.count
        ).filter(
            tuple_(SlotItemCount.room_id, SlotItemCount.slot_id, SlotItemCount.item_id).in_(count_keys)
        ).all()
        item_counts = {(r, s, i): c for r, s, i, c in counts_query}

    # 4. Load metadata (Players and Game Checksums)
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
            item_name_key = (rec_checksum, 'item', item.item_id)
            cache_keys_to_find.add(item_name_key)
            
        # B. Resolve Location Name (Uses Sender's Game)
        if sender_game and snd_checksum:
            location_name_key = (snd_checksum, 'location', item.location_id)
            cache_keys_to_find.add(location_name_key)

        receiver_name = receiver_obj.get('name', f"Player {receiver_id}") if receiver_obj else f"Player {receiver_id}"
        sender_name = sender_obj.get('name', f"Player {sender_id}") if sender_obj else f"Player {sender_id}"
        
        # Extract Aliases
        receiver_alias = receiver_obj.get('alias') if receiver_obj else None
        sender_alias = sender_obj.get('alias') if sender_obj else None

        history_pre_cache.append({
            "id": item.id,
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
            "_raw_loc_id": item.location_id,
            "receivedCount": item_counts.get((item.room_id, item.receiving_slot_id, item.item_id), 0)
        })

    # 5. Bulk Fetch Names from Cache
    name_cache_map = {}
    if cache_keys_to_find:
        cache_query = session.query(
            DatapackageCache.checksum,
            DatapackageCache.entity_type,
            DatapackageCache.entity_id,
            DatapackageCache.entity_name
        ).filter(
            tuple_(
                DatapackageCache.checksum,
                DatapackageCache.entity_type,
                DatapackageCache.entity_id
            ).in_(cache_keys_to_find)
        )
        name_cache_map = {
            (c.checksum, c.entity_type, c.entity_id): c.entity_name
            for c in cache_query.all()
        }

    # 6. Second Pass: Build Final Response
    history = []
    for temp_item in history_pre_cache:
        item_name = name_cache_map.get(temp_item["_item_name_key"]) or f"Item ID {temp_item['_raw_item_id']}"
        location_name = name_cache_map.get(temp_item["_loc_name_key"]) or f"Location ID {temp_item['_raw_loc_id']}"
        
        history.append({
            "id": temp_item["id"],
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
            "room_db_id": room.id,
            "tracker_id": temp_item["tracker_id"],
            "slot_id": temp_item["slot_id"],
            "host": temp_item["host"],
            "receivedCount": temp_item["receivedCount"]
        })

    return jsonify(history)


@bp.route('/history/sync', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def sync_history(current_user):
    """
    High-performance batch history sync endpoint.
    Accepts per-slot and per-room watermarks, performs isolated delta queries,
    and returns only new/modified items and hints along with updated watermarks.
    """
    data = request.json or {}
    session = Session()

    # 1. Fetch tracked rooms and slots for the current user
    user_tracked_slots = session.query(
        UserTrackedSlot.room_id, 
        UserTrackedSlot.slot_id,
        UserTrackedSlot.added_at
    ).filter_by(
        user_id=current_user.id
    ).all()

    if not user_tracked_slots:
        return jsonify({
            "new_items": [],
            "updated_hints": [],
            "item_watermarks": {},
            "hint_watermarks": {}
        })

    # Get all active subscriptions for room metadata mapping
    user_subs = session.query(UserRoomSubscription).filter_by(
        user_id=current_user.id,
        is_archived=False
    ).all()

    room_db_id_to_uuid = {}
    room_db_id_to_sub = {}
    room_uuid_to_sub = {}
    room_db_id_to_room = {}
    for sub in user_subs:
        if sub.room:
            room_db_id_to_uuid[sub.room_id] = sub.room.room_id
            room_db_id_to_sub[sub.room_id] = sub
            room_uuid_to_sub[sub.room.room_id] = sub
            room_db_id_to_room[sub.room_id] = sub.room

    # 2. Build Item Sync Watermarks & Query Filters
    tracked_set = set((slot.room_id, slot.slot_id) for slot in user_tracked_slots)
    
    item_watermarks_map = {}
    for item in data.get('items', []):
        r_id = item.get('room_db_id')
        s_id = item.get('slot_id')
        last_ts = item.get('last_timestamp')
        if (r_id, s_id) in tracked_set:
            item_watermarks_map[(r_id, s_id)] = last_ts

    # Backfill missing slots
    for (r_id, s_id) in tracked_set:
        if (r_id, s_id) not in item_watermarks_map:
            item_watermarks_map[(r_id, s_id)] = None

    # Execute isolated queries per slot to prevent starvation/crowding
    items = []
    for (r_id, s_id), last_ts in item_watermarks_map.items():
        room_uuid = room_db_id_to_uuid.get(r_id)
        if not room_uuid:
            continue
            
        slot_query = session.query(NotifiedItem).filter(
            NotifiedItem.room_id == room_uuid,
            NotifiedItem.receiving_slot_id == s_id
        )
        
        if last_ts:
            try:
                since_dt = datetime.fromisoformat(last_ts.replace('Z', '+00:00'))
                if since_dt.tzinfo:
                    since_dt = since_dt.replace(tzinfo=None)
                
                slot_items = slot_query.filter(
                    NotifiedItem.timestamp > since_dt
                ).order_by(NotifiedItem.id.asc()).limit(200).all()
            except (ValueError, TypeError):
                slot_items = slot_query.order_by(NotifiedItem.id.asc()).limit(200).all()
        else:
            # Backfill: fetch oldest 200 items in ascending order to allow progressive pagination
            slot_items = slot_query.order_by(NotifiedItem.id.asc()).limit(200).all()
            
        items.extend(slot_items)

    # 3. Build Hint Sync Watermarks & Query Filters
    hint_watermarks_map = {}
    for hint in data.get('hints', []):
        r_id = hint.get('room_db_id')
        last_upd = hint.get('last_updated')
        if r_id in room_db_id_to_uuid:
            hint_watermarks_map[r_id] = last_upd

    # Backfill missing rooms
    for r_id in room_db_id_to_uuid.keys():
        if r_id not in hint_watermarks_map:
            hint_watermarks_map[r_id] = None

    # Execute isolated queries per room for hints
    hints = []
    for r_id, last_upd in hint_watermarks_map.items():
        room_uuid = room_db_id_to_uuid.get(r_id)
        if not room_uuid:
            continue
            
        room_hint_query = session.query(NotifiedHint).filter(
            NotifiedHint.room_id == room_uuid
        )
        
        if last_upd:
            try:
                since_upd = datetime.fromisoformat(last_upd.replace('Z', '+00:00'))
                if since_upd.tzinfo:
                    since_upd = since_upd.replace(tzinfo=None)
                
                room_hints = room_hint_query.filter(
                    NotifiedHint.updated_at > since_upd
                ).order_by(NotifiedHint.updated_at.asc()).limit(100).all()
            except (ValueError, TypeError):
                room_hints = room_hint_query.order_by(NotifiedHint.updated_at.asc()).limit(100).all()
        else:
            # Backfill: fetch oldest 100 hints in ascending order to allow progressive pagination
            room_hints = room_hint_query.order_by(NotifiedHint.updated_at.asc()).limit(100).all()
            
        hints.extend(room_hints)

    # 4. Gather room metadata
    room_uuids = set(item.room_id for item in items) | set(hint.room_id for hint in hints)
    rooms_to_map = session.query(TrackedRoom).filter(TrackedRoom.room_id.in_(room_uuids)).all()
    room_map_by_uuid = {r.room_id: r for r in rooms_to_map}

    parsed_room_metadata = {}
    for room_uuid, room_data in room_map_by_uuid.items():
        try:
            players = json.loads(room_data.cached_players_json or '[]')
            if not isinstance(players, list): players = []
            
            game_checksums = json.loads(room_data.game_checksums_json or '{}')
            if not isinstance(game_checksums, dict): game_checksums = {}
            
            player_map = {p['slot_id']: p for p in players}
            game_map = {p['slot_id']: p.get('game') for p in players}
            
            parsed_room_metadata[room_uuid] = {
                'player_map': player_map,
                'game_map': game_map,
                'game_checksums': game_checksums
            }
        except Exception:
            parsed_room_metadata[room_uuid] = {
                'player_map': {},
                'game_map': {},
                'game_checksums': {}
            }

    # Fetch Slot Item Counts
    item_counts = {}
    if items:
        count_keys = set((item.room_id, item.receiving_slot_id, item.item_id) for item in items)
        counts_query = session.query(
            SlotItemCount.room_id, 
            SlotItemCount.slot_id, 
            SlotItemCount.item_id, 
            SlotItemCount.count
        ).filter(
            tuple_(SlotItemCount.room_id, SlotItemCount.slot_id, SlotItemCount.item_id).in_(count_keys)
        ).all()
        item_counts = {(r, s, i): c for r, s, i, c in counts_query}

    # Bulk Resolve Names from Cache
    cache_keys_to_find = set()
    for item in items:
        meta = parsed_room_metadata.get(item.room_id, {})
        game_checksums = meta.get('game_checksums', {})
        game_map = meta.get('game_map', {})
        
        receiver_game = game_map.get(item.receiving_slot_id, "Unknown")
        sender_game = game_map.get(item.sending_slot_id, "Unknown")
        
        rec_checksum = game_checksums.get(receiver_game)
        snd_checksum = game_checksums.get(sender_game)
        
        if receiver_game and rec_checksum:
            cache_keys_to_find.add((rec_checksum, 'item', item.item_id))
        if sender_game and snd_checksum:
            cache_keys_to_find.add((snd_checksum, 'location', item.location_id))

    for hint in hints:
        meta = parsed_room_metadata.get(hint.room_id, {})
        game_checksums = meta.get('game_checksums', {})
        game_map = meta.get('game_map', {})
        
        io_game = game_map.get(hint.item_owner_id, "Unknown")
        lo_game = game_map.get(hint.location_owner_id, "Unknown")
        
        io_checksum = game_checksums.get(io_game)
        lo_checksum = game_checksums.get(lo_game)
        
        if io_game and io_checksum:
            cache_keys_to_find.add((io_checksum, 'item', hint.item_id))
        if lo_game and lo_checksum:
            cache_keys_to_find.add((lo_checksum, 'location', hint.location_id))

    name_cache_map = {}
    if cache_keys_to_find:
        cache_query = session.query(
            DatapackageCache.checksum,
            DatapackageCache.entity_type,
            DatapackageCache.entity_id,
            DatapackageCache.entity_name
        ).filter(
            tuple_(
                DatapackageCache.checksum,
                DatapackageCache.entity_type,
                DatapackageCache.entity_id
            ).in_(cache_keys_to_find)
        )
        name_cache_map = {
            (c.checksum, c.entity_type, c.entity_id): c.entity_name
            for c in cache_query.all()
        }

    # 5. Build JSON Response Elements
    response_items = []
    for item in items:
        room_data = room_map_by_uuid.get(item.room_id)
        sub = room_uuid_to_sub.get(item.room_id)
        if not room_data or not sub:
            continue
            
        meta = parsed_room_metadata.get(item.room_id, {})
        player_map = meta.get('player_map', {})
        game_checksums = meta.get('game_checksums', {})
        game_map = meta.get('game_map', {})
        
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
        
        item_name = name_cache_map.get((rec_checksum, 'item', item.item_id)) or f"Item ID {item.item_id}"
        location_name = name_cache_map.get((snd_checksum, 'location', item.location_id)) or f"Location ID {item.location_id}"
        
        response_items.append({
            "id": item.id,
            "room_db_id": room_data.id,
            "room_alias": sub.alias,
            "icon_name": sub.icon_name,
            "playerName": receiver_name,
            "playerAlias": receiver_alias,
            "receivingGame": receiver_game,
            "itemName": item_name,
            "senderName": sender_name,
            "senderAlias": sender_alias,
            "senderGame": sender_game,
            "locationName": location_name,
            "isPlayerFinished": is_finished,
            "itemFlags": item.item_flags or 0,
            "timestamp": format_iso_z(item.timestamp),
            "tracker_id": room_data.tracker_id,
            "slot_id": receiver_id,
            "host": room_data.hostname,
            "receivedCount": item_counts.get((item.room_id, item.receiving_slot_id, item.item_id), 0)
        })

    response_hints = []
    for hint in hints:
        room_data = room_map_by_uuid.get(hint.room_id)
        sub = room_uuid_to_sub.get(hint.room_id)
        if not room_data or not sub:
            continue
            
        meta = parsed_room_metadata.get(hint.room_id, {})
        player_map = meta.get('player_map', {})
        game_checksums = meta.get('game_checksums', {})
        game_map = meta.get('game_map', {})
        
        io_id = hint.item_owner_id
        lo_id = hint.location_owner_id
        
        io_obj = player_map.get(io_id)
        lo_obj = player_map.get(lo_id)
        
        io_name = io_obj.get('name', f"Player {io_id}") if io_obj else f"Player {io_id}"
        io_alias = io_obj.get('alias') if io_obj else None
        
        lo_name = lo_obj.get('name', f"Player {lo_id}") if lo_obj else f"Player {lo_id}"
        lo_alias = lo_obj.get('alias') if lo_obj else None
        
        io_game = game_map.get(io_id, "Unknown")
        lo_game = game_map.get(lo_id, "Unknown")
        
        io_checksum = game_checksums.get(io_game)
        lo_checksum = game_checksums.get(lo_game)
        
        item_name = name_cache_map.get((io_checksum, 'item', hint.item_id)) or f"Item ID {hint.item_id}"
        location_name = name_cache_map.get((lo_checksum, 'location', hint.location_id)) or f"Location ID {hint.location_id}"
        
        response_hints.append({
            "id": hint.id,
            "room_db_id": room_data.id,
            "room_alias": sub.alias,
            "item_owner_id": io_id,
            "item_owner_name": io_name,
            "item_owner_alias": io_alias,
            "location_owner_id": lo_id,
            "location_owner_name": lo_name,
            "location_owner_alias": lo_alias,
            "item_name": item_name,
            "location_name": location_name,
            "is_found": hint.is_found,
            "timestamp": format_iso_z(hint.timestamp),
            "updated_at": format_iso_z(hint.updated_at),
            "item_flags": hint.item_flags or 0
        })

    # Compute advanced watermarks safely using absolute max calculations
    new_item_watermarks = {}
    for item in items:
        room_data = room_map_by_uuid.get(item.room_id)
        if room_data:
            key = f"{room_data.id}_{item.receiving_slot_id}"
            ts_str = format_iso_z(item.timestamp)
            if key not in new_item_watermarks or ts_str > new_item_watermarks[key]:
                new_item_watermarks[key] = ts_str

    new_hint_watermarks = {}
    for hint in hints:
        room_data = room_map_by_uuid.get(hint.room_id)
        if room_data:
            key = f"{room_data.id}"
            ts_str = format_iso_z(hint.updated_at)
            if key not in new_hint_watermarks or ts_str > new_hint_watermarks[key]:
                new_hint_watermarks[key] = ts_str

    return jsonify({
        "new_items": response_items,
        "updated_hints": response_hints,
        "item_watermarks": new_item_watermarks,
        "hint_watermarks": new_hint_watermarks
    })


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

    # 1. Get all (room_id, slot_id, added_at) tuples the user tracks.
    user_tracked_slots = session.query(
        UserTrackedSlot.room_id, 
        UserTrackedSlot.slot_id, 
        UserTrackedSlot.added_at
    ).filter_by(
        user_id=current_user.id
    ).all()

    if not user_tracked_slots:
        return jsonify([])

    slots_by_room_db_id = {}
    for room_db_id, slot_id, added_at in user_tracked_slots:
        if room_db_id not in slots_by_room_db_id:
            slots_by_room_db_id[room_db_id] = []
        slots_by_room_db_id[room_db_id].append((slot_id, added_at))

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

    since_timestamp = request.args.get('since')
    since_dt = None
    if since_timestamp:
        try:
            since_dt = datetime.fromisoformat(since_timestamp.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            pass

    filters = []
    for room_db_id, slots_info in slots_by_room_db_id.items():
        room_uuid = room_db_to_uuid.get(room_db_id)
        if not room_uuid:
            continue
        
        if since_dt:
            for slot_id, added_at in slots_info:
                added_at_utc = added_at.replace(tzinfo=timezone.utc) if added_at and added_at.tzinfo is None else added_at
                # If added_at is NULL (unknown) OR newer than since_dt, bypass the since filter
                # for a full backfill of this slot's history.
                if not added_at_utc or added_at_utc > since_dt:
                    # Sync backfill: bypass since filter for this slot
                    filters.append(
                        (NotifiedItem.room_id == room_uuid) &
                        (NotifiedItem.receiving_slot_id == slot_id)
                    )
                else:
                    # Normal: apply since_dt filter
                    filters.append(
                        (NotifiedItem.room_id == room_uuid) &
                        (NotifiedItem.receiving_slot_id == slot_id) &
                        (NotifiedItem.timestamp > since_dt)
                    )
        else:
            slot_ids = {s[0] for s in slots_info}
            filters.append(
                (NotifiedItem.room_id == room_uuid) &
                (NotifiedItem.receiving_slot_id.in_(slot_ids))
            )

    if not filters:
        return jsonify([])

    # 3. Build the Query
    query = session.query(NotifiedItem).filter(or_(*filters))

    # Order by DESC so the client gets the newest timestamp for next sync
    query = query.order_by(NotifiedItem.id.desc())

    # --- NEW: Pagination ---
    try:
        limit = max(1, min(int(request.args.get('limit', 50)), 100))
        offset = max(int(request.args.get('offset', 0)), 0)
    except (ValueError, TypeError):
        limit = 50
        offset = 0
    
    query = query.limit(limit).offset(offset)

    # 4. Pre-parse Room Metadata to avoid redundant JSON parsing in the loop
    parsed_room_metadata = {}
    for room_uuid, room_data in all_room_data.items():
        try:
            players = json.loads(room_data.cached_players_json or '[]')
            if not isinstance(players, list): players = []
            
            game_checksums = json.loads(room_data.game_checksums_json or '{}')
            if not isinstance(game_checksums, dict): game_checksums = {}
            
            player_map = {p['slot_id']: p for p in players}
            game_map = {p['slot_id']: p.get('game') for p in players}
            
            parsed_room_metadata[room_uuid] = {
                'player_map': player_map,
                'game_map': game_map,
                'game_checksums': game_checksums
            }
        except (json.JSONDecodeError, TypeError):
            parsed_room_metadata[room_uuid] = {
                'player_map': {},
                'game_map': {},
                'game_checksums': {}
            }

    # 5. Process the Results
    final_history_dicts = []
    items = query.all()

    if not items:
        return jsonify([])

    # 5a. Pre-calculate counts for these items from the materialized table
    count_keys = set((item.room_id, item.receiving_slot_id, item.item_id) for item in items)
    counts_query = session.query(
        SlotItemCount.room_id, 
        SlotItemCount.slot_id, 
        SlotItemCount.item_id, 
        SlotItemCount.count
    ).filter(
        tuple_(SlotItemCount.room_id, SlotItemCount.slot_id, SlotItemCount.item_id).in_(count_keys)
    ).all()
    item_counts = {(r, s, i): c for r, s, i, c in counts_query}

    history_pre_cache = []
    cache_keys_to_find = set()

    for item in items:
        room_data = all_room_data.get(item.room_id)
        if not room_data:
            continue
        
        sub = subs_map.get(room_data.id)
        if not sub:
            continue
        
        meta = parsed_room_metadata.get(item.room_id, {})
        player_map = meta.get('player_map', {})
        game_checksums = meta.get('game_checksums', {})
        game_map = meta.get('game_map', {})
        
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
            item_name_key = (rec_checksum, 'item', item.item_id)
            cache_keys_to_find.add(item_name_key)

        if sender_game and snd_checksum:
            location_name_key = (snd_checksum, 'location', item.location_id)
            cache_keys_to_find.add(location_name_key)

        history_pre_cache.append({
            "id": item.id,
            "room_db_id": room_data.id,
            "room_alias": sub.alias, 
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
            "itemFlags": item.item_flags or 0,
            "receivedCount": item_counts.get((item.room_id, item.receiving_slot_id, item.item_id), 0)
        })

    # Bulk Fetch Names for these items
    name_cache_map = {}
    if cache_keys_to_find:
        cache_query = session.query(
            DatapackageCache.checksum,
            DatapackageCache.entity_type,
            DatapackageCache.entity_id,
            DatapackageCache.entity_name
        ).filter(
            tuple_(
                DatapackageCache.checksum,
                DatapackageCache.entity_type,
                DatapackageCache.entity_id
            ).in_(cache_keys_to_find)
        )

        name_cache_map = {
            (c.checksum, c.entity_type, c.entity_id): c.entity_name
            for c in cache_query.all()
        }

    # Build Final lightweight dicts
    for temp_item in history_pre_cache:
        item_name = name_cache_map.get(temp_item["_item_name_key"]) or f"Item ID {temp_item['_raw_item_id']}"
        location_name = name_cache_map.get(temp_item["_loc_name_key"]) or f"Location ID {temp_item['_raw_loc_id']}"

        final_history_dicts.append({
            "id": temp_item["id"],
            "room_db_id": temp_item["room_db_id"], 
            "alias": temp_item["room_alias"], 
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
            "host": temp_item["host"],
            "receivedCount": temp_item["receivedCount"]
        })

    return jsonify(final_history_dicts)



# =============================================================================
# USER ENDPOINT
# =============================================================================

@bp.route('/users/me', methods=['GET'])
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
            'is_guest': False,
            'global_snooze_until': format_iso_z(current_user.global_snooze_until),
            'is_syncing_cheese': getattr(current_user, 'is_syncing_cheese', False)
        })

@bp.route('/users/me/tracked-slots', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_user_tracked_slots(current_user):
    session = Session()
    try:
        subscriptions = session.query(UserRoomSubscription).join(TrackedRoom).filter(
            UserRoomSubscription.user_id == current_user.id,
            ~TrackedRoom.room_id.startswith("PENDING_DISCOVERY")
        ).options(
            selectinload(UserRoomSubscription.room),
            selectinload(UserRoomSubscription.tracked_slots)
        ).order_by(UserRoomSubscription.alias).all()

        # --- Batch query: most recent activity per (room_uuid, slot_id) ---
        # Collect all (room_uuid, slot_id) pairs we need to look up
        all_room_uuids = set()
        room_db_to_uuid = {}
        for sub in subscriptions:
            if sub.room and not sub.room.room_id.startswith("PENDING_DISCOVERY"):
                all_room_uuids.add(sub.room.room_id)
                room_db_to_uuid[sub.room_id] = sub.room.room_id

        # Query max timestamp per (room_uuid, slot_id) from NotifiedItem
        from sqlalchemy import func as sa_func
        last_activity_map = {}  # (room_uuid, slot_id) -> datetime
        if all_room_uuids:
            activity_rows = session.query(
                NotifiedItem.room_id,
                NotifiedItem.receiving_slot_id,
                sa_func.max(NotifiedItem.timestamp).label('last_ts')
            ).filter(
                NotifiedItem.room_id.in_(all_room_uuids)
            ).group_by(
                NotifiedItem.room_id,
                NotifiedItem.receiving_slot_id
            ).all()
            for row in activity_rows:
                last_activity_map[(row.room_id, row.receiving_slot_id)] = row.last_ts

        response_data = []
        for sub in subscriptions:
            room_data = sub.room
            if not room_data: continue

            if room_data.room_id.startswith("PENDING_DISCOVERY"):
                continue

            try:
                players_json = json.loads(room_data.cached_players_json or '[]')
                if not isinstance(players_json, list):
                    players_json = []
            except (json.JSONDecodeError, TypeError):
                players_json = []

            players_map = {p['slot_id']: p for p in players_json}

            tracked_slots_list = []
            for slot in sorted(sub.tracked_slots, key=lambda s: s.slot_id):
                p_obj = players_map.get(slot.slot_id)
                p_name = p_obj.get('name', f"Player {slot.slot_id}") if p_obj else f"Player {slot.slot_id}"
                p_alias = p_obj.get('alias') if p_obj else None
                p_finished = p_obj.get('is_finished', False) if p_obj else False
                p_game = p_obj.get('game') if p_obj else None

                # Look up last activity for this specific slot
                slot_last_activity = last_activity_map.get((room_data.room_id, slot.slot_id))

                tracked_slots_list.append({
                    'slot_id': slot.slot_id,
                    'player_name': p_name,
                    'player_alias': p_alias,
                    'is_finished': p_finished,
                    'game': p_game,
                    'last_activity': format_iso_z(slot_last_activity),
                    'notify_progression': slot.notify_progression,
                    'notify_useful': slot.notify_useful,
                    'notify_hints': slot.notify_hints,
                    'notify_hints_remote_items': slot.notify_hints_remote_items,
                    'notify_finished': slot.notify_finished,
                    'use_condensed_messages': slot.use_condensed_messages,
                    'combine_notifications': slot.combine_notifications,
                    'suppress_own_events': slot.suppress_own_events,
                    'remove_emojis': slot.remove_emojis,
                    'suppress_self_found': slot.suppress_self_found,
                    'suppress_connected': slot.suppress_connected,
                    'snooze_until': format_iso_z(slot.snooze_until)
                })

            response_data.append({
                'room_db_id': sub.room_id,
                'room_id': room_data.room_id,
                'room_alias': sub.alias,
                'icon_name': sub.icon_name,
                'is_archived': sub.is_archived,
                'host': room_data.cached_full_address,
                'players': players_json,
                'tracked_slots': tracked_slots_list
            })

        return jsonify(response_data)
    finally:
        Session.remove()

@bp.route('/rooms/<int:room_db_id>/datapackage', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_room_datapackage(current_user, room_db_id):
    """
    Returns a consolidated datapackage for a room, including:
    - player_id -> player_name (alias or raw name)
    - item_id -> item_name (prefixed by slot checksum)
    - location_id -> location_name (prefixed by slot checksum)
    This is used by the client for name resolution in the terminal.
    """
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
        if not room:
            logging.warning(f"[DATAPACKAGE] 404: Room {room_db_id} not found in DB.")
            return jsonify({'error': 'Room not found'}), 404

        # 1. Player map
        try:
            players_json = json.loads(room.cached_players_json or '[]')
            game_checksums = json.loads(room.game_checksums_json or '{}')
        except (json.JSONDecodeError, TypeError):
            players_json = []
            game_checksums = {}

        player_map = {str(p['slot_id']): (p.get('alias') or p.get('name') or f"Player {p['slot_id']}") for p in players_json if 'slot_id' in p}
        # Add "Archipelago" (Slot 0)
        player_map["0"] = "Archipelago"
        
        logging.debug(f"[DATAPACKAGE] Room {room_db_id} has {len(player_map)} players and {len(game_checksums)} game checksums. Cache size: {len(room.cached_players_json or '')}")

        # 2. Item and Location maps
        items_map = {}
        item_flags = {}
        locations_map = {}
        slot_to_checksum = {}

        for p in players_json:
            slot_id = p.get('slot_id')
            game = p.get('game')
            if slot_id and game and game in game_checksums:
                slot_to_checksum[str(slot_id)] = game_checksums[game]

        checksums = list(set(game_checksums.values()))
        if checksums:
            entries = session.query(DatapackageCache).filter(DatapackageCache.checksum.in_(checksums)).all()
            for entry in entries:
                if entry.entity_type == 'item':
                    items_map[f"{entry.checksum}_{entry.entity_id}"] = entry.entity_name
                elif entry.entity_type == 'item_group':
                    items_map[f"{entry.checksum}_{entry.entity_id}"] = f"{entry.entity_name} (Group)"
                elif entry.entity_type == 'location':
                    locations_map[f"{entry.checksum}_{entry.entity_id}"] = entry.entity_name
                elif entry.entity_type == 'location_group':
                    locations_map[f"{entry.checksum}_{entry.entity_id}"] = f"{entry.entity_name} (Group)"

        logging.debug(f"[DATAPACKAGE] Returning {len(items_map)} items and {len(locations_map)} locations for room {room_db_id}")

        return jsonify({
            'players': player_map,
            'items': items_map,
            'item_flags': item_flags,
            'locations': locations_map,
            'slot_to_checksum': slot_to_checksum
        })
    finally:
        Session.remove()

@bp.route('/users/me/preferences', methods=['PUT'])
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

@bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/preferences', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_slot_preferences(current_user, room_db_id, slot_id):
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
        if 'combine_notifications' in data:
            tracked_slot.combine_notifications = data['combine_notifications']
        if 'suppress_own_events' in data:
            tracked_slot.suppress_own_events = data['suppress_own_events']
        if 'remove_emojis' in data:
            tracked_slot.remove_emojis = data['remove_emojis']
        if 'suppress_self_found' in data: # <--- NEW
            tracked_slot.suppress_self_found = data['suppress_self_found']
        if 'suppress_connected' in data:
            tracked_slot.suppress_connected = data['suppress_connected']
        session.commit()
        return jsonify({'message': 'Slot preferences updated successfully'}), 200
    except Exception as e:
        session.rollback()
        logging.error(f"Failed to update slot preferences for user {current_user.id} (room {room_db_id}, slot {slot_id}): {e}", exc_info=True)
        return jsonify({'error': 'An internal server error occurred.'}), 500
    finally:
        Session.remove()


@bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/thresholds', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_slot_thresholds(current_user, room_db_id, slot_id):
    session = Session()
    try:
        tracked_slot = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id,
            room_id=room_db_id,
            slot_id=slot_id
        ).first()
        if not tracked_slot:
            return jsonify({'error': 'Tracked slot not found'}), 404
        
        thresholds = session.query(SlotItemThreshold).filter_by(user_tracked_slot_id=tracked_slot.id).all()
        return jsonify([{
            'id': t.id,
            'item_name': t.item_name,
            'threshold': t.threshold
        } for t in thresholds])
    finally:
        Session.remove()

@bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/thresholds', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def update_slot_threshold(current_user, room_db_id, slot_id):
    data = request.json or {}
    item_name = data.get('item_name')
    threshold = data.get('threshold')
    
    if not item_name or threshold is None:
        return jsonify({'error': 'Missing item_name or threshold'}), 400
        
    session = Session()
    try:
        tracked_slot = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id,
            room_id=room_db_id,
            slot_id=slot_id
        ).first()
        if not tracked_slot:
            return jsonify({'error': 'Tracked slot not found'}), 404
            
        # Normalize for search but keep original for display
        search_name = item_name.lower().strip()
            
        obj = session.query(SlotItemThreshold).filter(
            SlotItemThreshold.user_tracked_slot_id == tracked_slot.id,
            func.lower(SlotItemThreshold.item_name) == search_name,
            SlotItemThreshold.threshold == threshold
        ).first()
        
        if not obj:
            obj = SlotItemThreshold(
                user_tracked_slot_id=tracked_slot.id,
                item_name=item_name.strip(), # Keep original casing
                threshold=threshold
            )
            session.add(obj)
            
        session.commit()
        return jsonify({'message': 'Threshold updated', 'item_name': item_name, 'threshold': threshold})
    finally:
        Session.remove()

@bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/thresholds/<int:threshold_id>', methods=['DELETE'])
@handle_db_errors
@log_api_call
@token_required
def delete_slot_threshold(current_user, room_db_id, slot_id, threshold_id):
    session = Session()
    try:
        tracked_slot = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id,
            room_id=room_db_id,
            slot_id=slot_id
        ).first()
        if not tracked_slot:
            return jsonify({'error': 'Tracked slot not found'}), 404
            
        obj = session.query(SlotItemThreshold).filter_by(
            id=threshold_id,
            user_tracked_slot_id=tracked_slot.id
        ).first()
        
        if not obj:
            return jsonify({'error': 'Threshold not found'}), 404
            
        session.delete(obj)
        session.commit()
        return jsonify({'message': 'Threshold deleted'})
    finally:
        Session.remove()

@bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/items', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_slot_available_items(current_user, room_db_id, slot_id):
    """
    Returns a list of all item names available for the game associated with this slot.
    Uses the DatapackageCache for the room's game checksums.
    """
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
        if not room:
            return jsonify({'error': 'Room not found'}), 404
            
        try:
            players = json.loads(room.cached_players_json or '[]')
        except (json.JSONDecodeError, TypeError):
            players = []
            
        slot_info = next((p for p in players if p.get('slot_id') == slot_id), None)
        if not slot_info:
            logging.warning(f"[{'ITEMS' if 'items' in request.path else 'LOCATIONS'}] 404: Slot {slot_id} not found in cache for room {room_db_id}. Cache size: {len(players)}")
            return jsonify({'error': f'Slot {slot_id} not found in room info cache'}), 404
            
        game = slot_info.get('game')
        if not game:
            return jsonify([])
            
        try:
            game_checksums = json.loads(room.game_checksums_json or '{}')
        except (json.JSONDecodeError, TypeError):
            game_checksums = {}
            
        checksum = game_checksums.get(game)
        if not checksum:
            return jsonify([])
            
        items_query = session.query(DatapackageCache.entity_name, DatapackageCache.entity_type).filter(
            DatapackageCache.checksum == checksum,
            DatapackageCache.entity_type.in_(['item', 'item_group'])
        ).distinct().all()
        
        results = []
        for name, etype in items_query:
            results.append({
                "name": name,
                "is_group": etype == 'item_group'
            })
        
        results.sort(key=lambda x: x['name'])
        return jsonify(results)
    finally:
        Session.remove()


@bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/locations', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required

def get_slot_available_locations(current_user, room_db_id, slot_id):
    """
    Returns a list of all location names available for the game associated with this slot.
    Uses the DatapackageCache for the room's game checksums.
    """
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
        if not room:
            return jsonify({'error': 'Room not found'}), 404
            
        try:
            players = json.loads(room.cached_players_json or '[]')
        except (json.JSONDecodeError, TypeError):
            players = []
            
        slot_info = next((p for p in players if p.get('slot_id') == slot_id), None)
        if not slot_info:
            logging.warning(f"[LOCATIONS] 404: Slot {slot_id} not found in cache for room {room_db_id}. Cache size: {len(players)}")
            return jsonify({'error': f'Slot {slot_id} not found in room info cache'}), 404
            
        game = slot_info.get('game')
        if not game:
            return jsonify([])
            
        try:
            game_checksums = json.loads(room.game_checksums_json or '{}')
        except (json.JSONDecodeError, TypeError):
            game_checksums = {}
            
        checksum = game_checksums.get(game)
        if not checksum:
            return jsonify([])
            
        locations_query = session.query(DatapackageCache.entity_name, DatapackageCache.entity_type).filter(
            DatapackageCache.checksum == checksum,
            DatapackageCache.entity_type.in_(['location', 'location_group'])
        ).distinct().all()
        
        results = []
        for name, etype in locations_query:
            results.append({
                "name": name,
                "is_group": etype == 'location_group'
            })
        
        results.sort(key=lambda x: x['name'])
        return jsonify(results)
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
            item_name_key = (item_checksum, 'item', hint.item_id)
            cache_keys_to_find.add(item_name_key)
            
        if location_owner_game and location_checksum:
            location_name_key = (location_checksum, 'location', hint.location_id)
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
            DatapackageCache.checksum,
            DatapackageCache.entity_type,
            DatapackageCache.entity_id,
            DatapackageCache.entity_name
        ).filter(
            tuple_(
                DatapackageCache.checksum,
                DatapackageCache.entity_type,
                DatapackageCache.entity_id
            ).in_(cache_keys_to_find)
        )
        name_cache_map = {
            (c.checksum, c.entity_type, c.entity_id): c.entity_name
            for c in cache_query.all()
        }

    for temp_data in temp_hint_data:
        hint = temp_data["hint_obj"]
        current_room_db_id = temp_data["room_db_id"]
        player_map = player_map_by_room.get(current_room_db_id, {})
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

# =============================================================================
# SNOOZE MANAGEMENT (NEW)
# =============================================================================

@bp.route('/users/me/snooze', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def set_global_snooze(current_user):
    """
    Sets a global snooze timer for the current user.
    Payload: { "duration_minutes": 60 }
    Sending 0 or negative clears the snooze.
    """
    data = request.json or {}
    duration = data.get('duration_minutes')

    if duration is None or not isinstance(duration, int):
        return jsonify({'error': 'duration_minutes (int) is required'}), 400

    session = Session()
    
    user = session.query(User).filter_by(id=current_user.id).first()
    
    if duration <= 0:
        user.global_snooze_until = None
        logging.info(f"[API] User {user.id} disabled global snooze.")
        message = "Global snooze disabled."
    else:
        # Calculate expiration time (UTC)
        snooze_until = datetime.utcnow() + timedelta(minutes=duration)
        user.global_snooze_until = snooze_until
        logging.info(f"[API] User {user.id} snoozed all notifications for {duration} mins.")
        message = f"App snoozed for {duration} minutes."

    session.commit()
    
    return jsonify({
        'message': message,
        'snooze_until': format_iso_z(user.global_snooze_until)
    })


@bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/snooze', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def set_slot_snooze(current_user, room_db_id, slot_id):
    """
    Sets a snooze timer for a specific tracked slot.
    Payload: { "duration_minutes": 60 }
    """
    data = request.json or {}
    duration = data.get('duration_minutes')

    if duration is None or not isinstance(duration, int):
        return jsonify({'error': 'duration_minutes (int) is required'}), 400

    session = Session()
    
    # [REFACTORED] Removed manual try/finally block
    slot = session.query(UserTrackedSlot).filter_by(
        user_id=current_user.id,
        room_id=room_db_id, # Ensure this matches your fixed model attribute (room_id)
        slot_id=slot_id
    ).first()

    if not slot:
        return jsonify({'error': 'Tracked slot not found'}), 404

    if duration <= 0:
        slot.snooze_until = None
        logging.info(f"[API] User {current_user.id} unsnoozed slot {slot_id} in room {room_db_id}.")
        message = "Slot snooze disabled."
    else:
        snooze_until = datetime.utcnow() + timedelta(minutes=duration)
        slot.snooze_until = snooze_until
        logging.info(f"[API] User {current_user.id} snoozed slot {slot_id} for {duration} mins.")
        message = f"Player snoozed for {duration} minutes."

    session.commit()

    return jsonify({
        'message': message,
        'snooze_until': format_iso_z(slot.snooze_until)
    })

@bp.route('/users/me/test-notification', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def send_test_notification(current_user):
    """
    Triggers a fake push notification to all of the user's registered devices.
    Useful for debugging FCM and Notification Actions.
    """
    get_firebase_app()
    session = Session()
    try:
        # 1. Get user's devices
        devices = session.query(Device).filter_by(user_id=current_user.id).all()
        if not devices:
            return jsonify({'error': 'No devices registered. Open the app to register.'}), 404

        tokens = [d.fcm_token for d in devices]
        success_count = 0
        
        # 2. Send a message to each token
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