import logging
import json
import os
import requests
import jwt
import asyncio
import traceback # <-- This is needed
from datetime import datetime, timezone, timedelta
from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.exc import OperationalError, IntegrityError
from sqlalchemy import or_

from . import Session
from .models import (
    User, Device, TrackedRoom, UserRoomSubscription, UserTrackedSlot, 
    DatapackageCache, NotifiedItem, NotifiedHint
)

bp = Blueprint('api', __name__)

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
        
        logging.warning(f"[API] Call: {request.method} {request.path} | Payload: {payload}")
        
        try:
            # 2. Execute the actual API function
            response = f(*args, **kwargs)
            
            # 3. Log Response
            response_data = ""
            if hasattr(response, 'get_data'): # This is a Flask Response object
                try:
                    # Truncate long responses (like history) to avoid spamming logs
                    response_data = response.get_data(as_text=True)[:500] 
                except Exception:
                    response_data = "Error getting response data"
            else:
                response_data = str(response) # Should not happen with jsonify, but a fallback.

            logging.warning(f"[API] Response: {request.path} | Body: {response_data}...")
            return response
        
        except Exception as e:
            # 4. Log any exceptions
            logging.error(f"[API] Error: {request.path} | Exception: {e}", exc_info=True)
            # Re-raise the exception to be handled by @handle_db_errors or Flask
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
                return jsonify({'error': 'Malformed Authorization header'}), 401

        if not token:
            return jsonify({'error': 'Authentication token is missing'}), 401

        try:
            secret = current_app.config['SECRET_KEY']
            data = jwt.decode(token, secret, algorithms=['HS256'])

            session = Session()
            current_user = session.query(User).filter_by(id=data['user_id']).first()
            if not current_user:
                return jsonify({'error': 'User not found'}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        except Exception as e:
            session.rollback()
            return jsonify({'error': f'Token processing error: {e}'}), 500
        finally:
            session.close()

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
            print(f"[API_ERROR] Database locked or operational error: {e}")
            return jsonify({'error': 'Database is busy, please try again.'}), 503
        except IntegrityError as e:
            session.rollback()
            print(f"[API_ERROR] Database integrity error: {e}")
            return jsonify({'error': 'A record with this value already exists.'}), 409
        except Exception as e:
            session.rollback()
            print(f"[API_ERROR] An unhandled API error occurred: {e}")
            traceback.print_exc() 
            return jsonify({'error': f'An internal server error occurred: {e}'}), 500
        finally:
            Session.remove()
    return decorated_function

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
    If the token already exists, it updates its user_id.
    """
    data = request.json
    fcm_token = data.get('fcm_token')
    if not fcm_token:
        return jsonify({'error': 'Missing fcm_token'}), 400

    session = Session()
    device = session.query(Device).filter_by(fcm_token=fcm_token).first()
    
    if device:
        if device.user_id != current_user.id:
            device.user_id = current_user.id
            print(f"[API] Re-assigned existing device token to user {current_user.id}")
        else:
            print(f"[API] Refreshed device token for user {current_user.id}")
    else:
        device = Device(fcm_token=fcm_token, user_id=current_user.id)
        session.add(device)
        print(f"[API] Registered new device for user {current_user.id}")

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
    Gets the list of rooms the current user is subscribed to,
    along with their tracking status.
    """
    session = Session()
    subscriptions = session.query(UserRoomSubscription).filter_by(user_id=current_user.id).all()
    
    rooms_list = []
    for sub in subscriptions:
        room = sub.room
        tracked_count = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id, 
            room_id=room.id
        ).count()
        
        rooms_list.append({
            'id': room.id,
            'room_id': room.room_id,
            'alias': sub.alias,
            'icon_name': sub.icon_name,
            'host': room.cached_full_address, # Corrected
            'is_complete': room.is_complete,
            'is_suspended': room.is_suspended,
            'total_slots_count': room.cached_total_slots,
            'tracked_slots_count': tracked_count
        })

    return jsonify(rooms_list)

@bp.route('/rooms', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def add_room(current_user):
    """
    Adds a new room to the global tracking list and subscribes the
    current user to it.
    """
    data = request.json
    room_url = data.get('room_url')
    alias = data.get('alias')
    icon_name = data.get('icon_name')

    if not room_url:
        return jsonify({'error': 'Missing room_url'}), 400
    if not alias:
        return jsonify({'error': 'Missing alias'}), 400

    try:
        parsed_url = urlparse(room_url)
        hostname = parsed_url.hostname
        room_id = parsed_url.path.split('/')[-1]
    except Exception as e:
        return jsonify({'error': f'Invalid room_url: {e}'}), 400

    if not hostname or not room_id:
        return jsonify({'error': 'Could not parse hostname or room_id from URL'}), 400

    session = Session()
    room = session.query(TrackedRoom).filter_by(room_id=room_id).first()

    if not room:
        print(f"[API] First time seeing room {room_id}. Creating global record.")
        try:
            # Ping the room status to get the port
            status_url = f"https://{hostname}/api/room_status/{room_id}"
            response = requests.get(status_url, timeout=10)
            response.raise_for_status()
            status_data = response.json()
            port = status_data.get('last_port', '')
            
            # --- THIS IS THE FIX ---
            # Format the player data correctly before saving
            players_raw = status_data.get('players', [])
            player_list = [{'slot_id': i + 1, 'name': p[0], 'game': p[1]} for i, p in enumerate(players_raw)]
            players_json = json.dumps(player_list)
            total_slots = len(player_list)
            # --- END OF FIX ---

            room = TrackedRoom(
                room_id=room_id,
                hostname=hostname,
                cached_full_address=f"{hostname}:{port}",
                cached_players_json=players_json, # Save the correctly formatted JSON
                cached_total_slots=total_slots
            )
            session.add(room)
            session.flush() # Flush to get the room.id
        
        except requests.exceptions.RequestException as e:
            print(f"[API_ERROR] Failed to fetch initial room status for {room_id}: {e}")
            return jsonify({'error': 'Could not connect to the room to verify its status.'}), 404
        except Exception as e:
            session.rollback()
            print(f"[API_ERROR] Failed to process room status for {room_id}: {e}")
            return jsonify({'error': f'Error processing room status: {e}'}), 500

    # Now subscribe the user
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
    
    room.is_suspended = False # Wake up the room if it was suspended

    session.commit()
    return jsonify({'message': f"Now tracking room '{alias}'."}), 201


@bp.route('/rooms/<int:room_db_id>', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_subscription(current_user, room_db_id):
    """
    Updates a user's subscription details for a room (e.g., alias).
    """
    data = request.json
    alias = data.get('alias')
    icon_name = data.get('icon_name')

    if not alias and not icon_name:
        return jsonify({'error': 'Missing alias or icon_name'}), 400

    session = Session()
    subscription = session.query(UserRoomSubscription).filter_by(
        user_id=current_user.id,
        room_id=room_db_id
    ).first()

    if not subscription:
        return jsonify({'error': 'Not subscribed to this room'}), 403

    if alias:
        subscription.alias = alias
    if icon_name:
        subscription.icon_name = icon_name

    session.commit()
    return jsonify({'message': 'Subscription updated.'})


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

    # The relationship cascade should handle deleting UserTrackedSlot entries
    session.delete(subscription)
    session.commit()
    
    print(f"[API] User {current_user.id} unsubscribed from room {room_db_id}")
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
    Returns the list of players for a specific room, along with which ones
    the current user is tracking.
    """
    session = Session()
    subscription = session.query(UserRoomSubscription).filter_by(
        user_id=current_user.id,
        room_id=room_db_id
    ).first()
    if not subscription:
        return jsonify({'error': 'Not subscribed to this room'}), 403

    room = subscription.room
    if not room.cached_players_json:
        # Attempt to fetch players if missing (e.g., if setup hasn't run)
        try:
            status_url = f"https://{room.hostname}/api/room_status/{room.room_id}"
            response = requests.get(status_url, timeout=10)
            response.raise_for_status()
            status_data = response.json()
            # Format the data correctly, just like in add_room
            players_raw = status_data.get('players', [])
            player_list = [{'slot_id': i + 1, 'name': p[0], 'game': p[1]} for i, p in enumerate(players_raw)]
            room.cached_players_json = json.dumps(player_list)
            room.cached_total_slots = len(player_list)
            session.commit()
            print(f"[API] Fetched missing player list for room {room.room_id}")
        except Exception as e:
            print(f"[API_ERROR] Failed to fetch players for room {room.room_id}: {e}")
            return jsonify({'error': 'Player data not yet cached for this room. Please wait.'}), 404

    try:
        players = json.loads(room.cached_players_json)
    except json.JSONDecodeError:
        players = []

    tracked_slots_query = session.query(UserTrackedSlot.slot_id).filter_by(
        user_id=current_user.id,
        room_id=room_db_id
    )
    tracked_slot_ids = {slot.slot_id for slot in tracked_slots_query.all()}
    
    player_list_with_tracking = []
    for p in players:
        # This loop now correctly receives a dictionary
        player_list_with_tracking.append({
            'slot_id': p['slot_id'],
            'name': p['name'],
            'game': p['game'],
            'is_tracked': p['slot_id'] in tracked_slot_ids
        })

    return jsonify(player_list_with_tracking)


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

    # --- History pre-fill logic has been REMOVED ---
    
    # --- Update the user's tracked slots ---
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

    if slots_to_add:
        objects_to_add = [
            UserTrackedSlot(user_id=current_user.id, room_id=room_db_id, slot_id=slot_id)
            for slot_id in slots_to_add if isinstance(slot_id, int) and slot_id > 0
        ]
        session.bulk_save_objects(objects_to_add)

    session.commit()
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
    current user is tracking.
    """
    session = Session()
    room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
    if not room:
        return jsonify({'error': 'Room not found'}), 404

    user_tracked_slots = session.query(UserTrackedSlot.slot_id).filter_by(
        user_id=current_user.id,
        room_id=room.id
    ).all()
    tracked_slot_ids = {slot[0] for slot in user_tracked_slots}

    if not tracked_slot_ids:
        return jsonify([]) 

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

    # --- Limit removed to allow full history, per our 16k vs 2.6k discussion ---
    items = query.order_by(NotifiedItem.id.desc()).all()

    try:
        game_checksums = json.loads(room.game_checksums_json or '{}')
        players = json.loads(room.cached_players_json or '[]')
    except json.JSONDecodeError:
        return jsonify({'error': 'Room data is corrupt or missing.'}), 500
        
    name_map = {p['slot_id']: p['name'] for p in players}
    game_map = {p['slot_id']: p['game'] for p in players}

    history = []
    for item in items:
        receiver_name = name_map.get(item.receiving_slot_id, f"Player {item.receiving_slot_id}")
        receiver_game = game_map.get(item.receiving_slot_id, "Unknown")
        game_checksum = game_checksums.get(receiver_game)

        item_name = session.query(DatapackageCache.entity_name).filter_by(
            game=receiver_game,
            checksum=game_checksum,
            entity_type='item',
            entity_id=item.item_id
        ).scalar() or f"Item ID {item.item_id}"

        history.append({
            "message": f"{receiver_name} received: {item_name}",
            "timestamp": item.timestamp.replace(tzinfo=timezone.utc).isoformat(),
            "tracker_id": room.tracker_id,
            "slot_id": item.receiving_slot_id,
        })

    return jsonify(history)


@bp.route('/history/items', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_global_item_history(current_user):
    """
    Gets a global, aggregated item history feed for the current user,
    containing all relevant events from all rooms they track.
    """
    session = Session()

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

    room_map = {
        room.id: room.room_id for room in
        session.query(TrackedRoom).filter(TrackedRoom.id.in_(slots_by_room_db_id.keys()))
    }

    filters = []
    for room_db_id, slot_ids in slots_by_room_db_id.items():
        room_uuid = room_map.get(room_db_id)
        if room_uuid:
            filters.append(
                (NotifiedItem.room_id == room_uuid) &
                (NotifiedItem.receiving_slot_id.in_(slot_ids))
            )

    if not filters:
        return jsonify([])

    query = session.query(NotifiedItem).filter(or_(*filters))

    since_timestamp = request.args.get('since')
    if since_timestamp:
        try:
            since_dt = datetime.fromisoformat(since_timestamp.replace('Z', '+00:00'))
            query = query.filter(NotifiedItem.timestamp > since_dt)
        except (ValueError, TypeError):
            pass

    # --- Limit removed to allow full history, per our 16k vs 2.6k discussion ---
    items = query.order_by(NotifiedItem.id.desc()).all()

    all_room_data = {
        r.room_id: r for r in
        session.query(TrackedRoom).filter(TrackedRoom.room_id.in_({i.room_id for i in items}))
    }

    history = []
    for item in items:
        room_data = all_room_data.get(item.room_id)
        if not room_data:
            continue
            
        sub = session.query(UserRoomSubscription).filter_by(user_id=current_user.id, room_id=room_data.id).first()
        if not sub:
            continue
        
        try:
            players = json.loads(room_data.cached_players_json or '[]')
            game_checksums = json.loads(room_data.game_checksums_json or '{}')
        except json.JSONDecodeError:
            continue # Skip this item if room data is bad

        name_map = {p['slot_id']: p['name'] for p in players}
        game_map = {p['slot_id']: p['game'] for p in players}

        receiver_name = name_map.get(item.receiving_slot_id, f"Player {item.receiving_slot_id}")
        receiver_game = game_map.get(item.receiving_slot_id, "Unknown")
        game_checksum = game_checksums.get(receiver_game)

        item_name = session.query(DatapackageCache.entity_name).filter_by(
            game=receiver_game,
            checksum=game_checksum,
            entity_type='item',
            entity_id=item.item_id
        ).scalar() or f"Item ID {item.item_id}"

        history.append({
            "db_id": room_data.id, 
            "alias": sub.alias, 
            "icon_name": sub.icon_name,
            "message": f"{receiver_name} received: {item_name}",
            "timestamp": item.timestamp.replace(tzinfo=timezone.utc).isoformat(),
            "tracker_id": room_data.tracker_id,
            "slot_id": item.receiving_slot_id
        })

    return jsonify(history)

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
    """
    base_url = "https://cdn.discordapp.com"
    if current_user.discord_avatar_hash:
        avatar_url = f"{base_url}/avatars/{current_user.discord_id}/{current_user.discord_avatar_hash}.png"
    else:
        # Default avatar logic
        try:
            discriminator_int = int(current_user.discord_username.split('#')[-1]) % 5
        except (ValueError, IndexError):
            discriminator_int = 0 # Fallback
        avatar_url = f"{base_url}/embed/avatars/{discriminator_int}.png"
        
    return jsonify({
        'discord_id': current_user.discord_id,
        'username': current_user.discord_username,
        'avatar_url': avatar_url
    })