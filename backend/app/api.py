import logging  # <-- NEW
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
from sqlalchemy.orm import selectinload, aliased
from sqlalchemy import or_, desc

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
        
        # --- CHANGED: Use DEBUG for high-frequency logs ---
        logging.debug(f"[API] Call: {request.method} {request.path} | Payload: {payload}")
        
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

            # --- CHANGED: Use DEBUG for high-frequency logs ---
            logging.debug(f"[API] Response: {request.path} | Body: {response_data}...")
            return response
        
        except Exception as e:
            # 4. Log any exceptions (This was already correct)
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
                logging.warning(f"Malformed Authorization header from {request.remote_addr}.")
                return jsonify({'error': 'Malformed Authorization header'}), 401

        if not token:
            logging.warning(f"Missing auth token from {request.remote_addr}.")
            return jsonify({'error': 'Authentication token is missing'}), 401

        session = None  # <-- FIX 1: Initialize session to None
        try:
            secret = current_app.config['SECRET_KEY']
            data = jwt.decode(token, secret, algorithms=['HS256'])

            session = Session() # <-- Session is created
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
            if session:  # <-- FIX 2: Check if session exists before rollback
                session.rollback()
            logging.error(f"Token processing error: {e}", exc_info=True)
            return jsonify({'error': f'Token processing error: {e}'}), 500
        finally:
            if session:  # <-- FIX 3: Check if session exists before removing
                Session.remove()  # <-- THE CRITICAL FIX: Was session.close()
                
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
            # --- CHANGED: print -> logging.error ---
            logging.error(f"[API_ERROR] Database locked or operational error: {e}")
            return jsonify({'error': 'Database is busy, please try again.'}), 503
        except IntegrityError as e:
            session.rollback()
            # --- CHANGED: print -> logging.warning ---
            logging.warning(f"[API_ERROR] Database integrity error: {e}")
            return jsonify({'error': 'A record with this value already exists.'}), 409
        except Exception as e:
            session.rollback()
            # --- CHANGED: print -> logging.error (and removed traceback) ---
            logging.error(f"[API_ERROR] An unhandled API error occurred: {e}", exc_info=True)
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
            # --- CHANGED: print -> logging.info ---
            logging.info(f"[API] Re-assigned existing device token to user {current_user.id}")
        else:
            # --- CHANGED: print -> logging.info ---
            logging.info(f"[API] Refreshed device token for user {current_user.id}")
    else:
        device = Device(fcm_token=fcm_token, user_id=current_user.id)
        session.add(device)
        # --- CHANGED: print -> logging.info ---
        logging.info(f"[API] Registered new device for user {current_user.id}")

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
        # --- CHANGED: print -> logging.info ---
        logging.info(f"[API] First time seeing room {room_id}. Creating global record.")
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
            # --- CHANGED: print -> logging.error ---
            logging.error(f"[API_ERROR] Failed to fetch initial room status for {room_id}: {e}")
            return jsonify({'error': 'Could not connect to the room to verify its status.'}), 404
        except Exception as e:
            session.rollback()
            # --- CHANGED: print -> logging.error ---
            logging.error(f"[API_ERROR] Failed to process room status for {room_id}: {e}", exc_info=True)
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
    
    # --- CHANGED: print -> logging.info ---
    logging.info(f"[API] User {current_user.id} unsubscribed from room {room_db_id}")
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

        players_list = json.loads(room.cached_players_json or '[]')

        # --- MODIFICATION START ---

        # Get all tracked slots for this user in this room in one query
        tracked_slots_query = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id,
            room_id=room_db_id
        ).all()
        
        # Create a dict for fast lookup: {slot_id: UserTrackedSlot}
        tracked_slots_map = {ts.slot_id: ts for ts in tracked_slots_query}

        response_players = []
        for p in players_list:
            slot_id = p.get('slot_id')
            tracked_slot_entry = tracked_slots_map.get(slot_id)

            response_players.append({
                'slot_id': slot_id,
                'name': p.get('name'),
                'game': p.get('game'),
                'is_tracked': tracked_slot_entry is not None,
                
                # Add these new keys
                'notify_progression': tracked_slot_entry.notify_progression if tracked_slot_entry else None,
                'notify_useful': tracked_slot_entry.notify_useful if tracked_slot_entry else None,
                'notify_hints': tracked_slot_entry.notify_hints if tracked_slot_entry else None
            })
        
        # --- MODIFICATION END ---
            
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

    # --- History pre-fill logic has been REMOVED (This is correct) ---
    
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
        logging.info(f"[API] User {current_user.id} untracked {len(slots_to_remove)} slots in room {room_db_id}.")

    if slots_to_add:
        objects_to_add = [
            UserTrackedSlot(user_id=current_user.id, room_id=room_db_id, slot_id=slot_id)
            for slot_id in slots_to_add if isinstance(slot_id, int) and slot_id > 0
        ]
        session.bulk_save_objects(objects_to_add)
        logging.info(f"[API] User {current_user.id} tracked {len(objects_to_add)} new slots in room {room_db_id}.")

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

    # --- Limit removed (This is correct based on our discussion) ---
    items = query.order_by(NotifiedItem.id.desc()).all()

    try:
        game_checksums = json.loads(room.game_checksums_json or '{}')
        players = json.loads(room.cached_players_json or '[]')
    except json.JSONDecodeError:
        logging.error(f"[API_ERROR] Room data for {room_db_id} is corrupt.", exc_info=True)
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

    # Query 1: Get all (room_id, slot_id) tuples the user tracks.
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

    # Query 2: Get a map of {room_db_id: room_uuid}.
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

    # Query 3: Get all NotifiedItem objects that match the filters.
    query = session.query(NotifiedItem).filter(or_(*filters))

    since_timestamp = request.args.get('since')
    if since_timestamp:
        try:
            since_dt = datetime.fromisoformat(since_timestamp.replace('Z', '+00:00'))
            query = query.filter(NotifiedItem.timestamp > since_dt)
        except (ValueError, TypeError):
            pass

    items = query.order_by(NotifiedItem.id.desc()).all()
    if not items:
        return jsonify([])

    # Query 4: Get ALL room data for all items found. (This part was already optimized)
    all_room_data = {
        r.room_id: r for r in
        session.query(TrackedRoom).filter(TrackedRoom.room_id.in_({i.room_id for i in items}))
    }

    # --- OPTIMIZATION 1: Fix N+1 query for Subscriptions ---
    # Get all relevant room_db_ids from the rooms we just fetched
    relevant_room_db_ids = {r.id for r in all_room_data.values()}
    
    # Fetch all user subscriptions for these rooms in ONE query
    subs_query = session.query(UserRoomSubscription).filter(
        UserRoomSubscription.user_id == current_user.id,
        UserRoomSubscription.room_id.in_(relevant_room_db_ids)
    )
    # Create a fast lookup map: {room_db_id: subscription}
    subs_map = {sub.room_id: sub for sub in subs_query.all()}
    # --- END OPTIMIZATION 1 ---

    history_pre_cache = []
    cache_keys_to_find = set()

    for item in items:
        room_data = all_room_data.get(item.room_id)
        if not room_data:
            continue
        
        # Use the map (O(1) lookup) instead of a query
        sub = subs_map.get(room_data.id)
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

        # --- OPTIMIZATION 2: Gather keys for name lookup ---
        item_name_key = None
        if receiver_game and game_checksum:
            # This is the unique key for an item name
            item_name_key = (receiver_game, game_checksum, 'item', item.item_id)
            cache_keys_to_find.add(item_name_key)
        # --- END OPTIMIZATION 2 ---

        history_pre_cache.append({
            "db_id": room_data.id, 
            "alias": sub.alias, 
            "icon_name": sub.icon_name,
            "receiver_name": receiver_name,
            "timestamp": item.timestamp.replace(tzinfo=timezone.utc).isoformat(),
            "tracker_id": room_data.tracker_id,
            "slot_id": item.receiving_slot_id,
            "_name_key": item_name_key, # Store key for lookup
            "_raw_item_id": item.item_id # Fallback
        })

    # --- OPTIMIZATION 2: Fetch all names in ONE query ---
    name_cache_map = {}
    if cache_keys_to_find:
        cache_filters = []
        for game, checksum, etype, eid in cache_keys_to_find:
            cache_filters.append(
                (DatapackageCache.game == game) &
                (DatapackageCache.checksum == checksum) &
                (DatapackageCache.entity_type == etype) &
                (DatapackageCache.entity_id == eid)
            )
        
        # This is now Query 5, running outside the loop
        cache_query = session.query(
            DatapackageCache.game,
            DatapackageCache.checksum,
            DatapackageCache.entity_type,
            DatapackageCache.entity_id,
            DatapackageCache.entity_name
        ).filter(or_(*cache_filters))

        # Create a fast lookup map: {(game, checksum, type, id): name}
        name_cache_map = {
            (c.game, c.checksum, c.entity_type, c.entity_id): c.entity_name
            for c in cache_query.all()
        }
    # --- END OPTIMIZATION 2 ---

    # Now, build the final history list by populating the names
    # This loop is fast and in-memory
    history = []
    for temp_item in history_pre_cache:
        # Look up the name in our map
        item_name = name_cache_map.get(temp_item["_name_key"]) or f"Item ID {temp_item['_raw_item_id']}"
        
        # Build the final object for the API
        history.append({
            "db_id": temp_item["db_id"], 
            "alias": temp_item["alias"], 
            "icon_name": temp_item["icon_name"],
            "message": f"{temp_item['receiver_name']} received: {item_name}",
            "timestamp": temp_item["timestamp"],
            "tracker_id": temp_item["tracker_id"],
            "slot_id": temp_item["slot_id"]
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
        'avatar_url': avatar_url,
        'notify_progression_default': current_user.notify_progression_default,
        'notify_useful_default': current_user.notify_useful_default,
        'notify_hints_default': current_user.notify_hints_default
    })

@bp.route('/users/me/tracked-slots', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_user_tracked_slots(current_user):
    """
    Returns a list of all rooms and slots the authenticated user is tracking,
    including their notification preferences for each slot.
    """
    session = Session()
    try:
        # Fetch all subscriptions for the user, eagerly loading related rooms and slots
        subscriptions = session.query(UserRoomSubscription).filter_by(user_id=current_user.id).options(
            selectinload(UserRoomSubscription.room),
            selectinload(UserRoomSubscription.tracked_slots)
        ).order_by(UserRoomSubscription.alias).all()

        response_data = []
        for sub in subscriptions:
            room_data = sub.room
            if not room_data: continue # Skip if room somehow doesn't exist

            # Get player names from the cached JSON for this room
            players_map = {p['slot_id']: p['name'] for p in json.loads(room_data.cached_players_json or '[]')}

            tracked_slots_list = []
            for slot in sorted(sub.tracked_slots, key=lambda s: s.slot_id):
                tracked_slots_list.append({
                    'slot_id': slot.slot_id,
                    'player_name': players_map.get(slot.slot_id, f"Player {slot.slot_id}"),
                    'notify_progression': slot.notify_progression,
                    'notify_useful': slot.notify_useful,
                    'notify_hints': slot.notify_hints
                })

            response_data.append({
                'room_db_id': sub.room_id,
                'room_alias': sub.alias,
                'icon_name': sub.icon_name,
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
    data = request.json
    session = Session()
    try:
        user = session.query(User).filter_by(id=current_user.id).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Update fields only if they are present in the request
        if 'notify_progression' in data:
            user.notify_progression_default = bool(data['notify_progression'])
        if 'notify_useful' in data:
            user.notify_useful_default = bool(data['notify_useful'])
        if 'notify_hints' in data:
            user.notify_hints_default = bool(data['notify_hints'])

        session.commit()
        return jsonify({'message': 'Preferences updated successfully'}), 200
    except Exception as e:
        session.rollback()
        # --- NEW: Added logging ---
        logging.error(f"Failed to update preferences for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'error': f'Failed to update preferences: {e}'}), 500
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
    data = request.json
    session = Session()
    try:
        # Find the specific slot the user is tracking
        tracked_slot = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id,
            room_id=room_db_id,
            slot_id=slot_id
        ).first()

        if not tracked_slot:
            return jsonify({'error': 'Tracked slot not found'}), 404

        # Update fields. 'None' is a valid value to "unset" the override.
        if 'notify_progression' in data:
            tracked_slot.notify_progression = data['notify_progression']
        if 'notify_useful' in data:
            tracked_slot.notify_useful = data['notify_useful']
        if 'notify_hints' in data:
            tracked_slot.notify_hints = data['notify_hints']

        session.commit()
        return jsonify({'message': 'Slot preferences updated successfully'}), 200
    except Exception as e:
        session.rollback()
        # --- NEW: Added logging ---
        logging.error(f"Failed to update slot preferences for user {current_user.id} (room {room_db_id}, slot {slot_id}): {e}", exc_info=True)
        return jsonify({'error': f'Failed to update slot preferences: {e}'}), 500
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

    # Base query for hints in relevant rooms
    hints_query = session.query(NotifiedHint).filter(
        NotifiedHint.room_id.in_(relevant_room_uuids)
    )

    # --- NEW: Filter by is_found status ---
    if not include_found:
        hints_query = hints_query.filter(NotifiedHint.is_found == False)
    # --- END NEW ---

    hints_query = hints_query.order_by(desc(NotifiedHint.id)) # Order by ID assuming it correlates with time


    # Apply timestamp filter if provided
    if since_timestamp:
        try:
            since_dt = datetime.fromisoformat(since_timestamp.replace('Z', '+00:00'))
            # Assuming NotifiedHint has a timestamp field (add one if needed!)
            # If not, we might need a different approach for 'since'
            if hasattr(NotifiedHint, 'timestamp'):
                 hints_query = hints_query.filter(NotifiedHint.timestamp > since_dt)
            else:
                 # If no timestamp, 'since' might be hard to implement reliably without storing it
                 # For now, let's proceed assuming we might fetch more than needed without timestamp
                 # --- CHANGED: print -> logging.warning ---
                 logging.warning(f"[HINT_API_WARN] 'since' parameter provided but NotifiedHint has no timestamp column.")

        except ValueError:
            # --- CHANGED: print -> logging.warning ---
            logging.warning(f"[HINT_API_WARN] Invalid 'since' timestamp format: {since_timestamp}")


    all_relevant_hints = hints_query.all()

    hints_for_you = []
    hints_by_you = []

    # We need datapackage cache for names
    # Create aliases for cleaner joins
    ItemOwnerCache = aliased(DatapackageCache)
    LocationOwnerCache = aliased(DatapackageCache)
    ItemNameCache = aliased(DatapackageCache)
    LocationNameCache = aliased(DatapackageCache)

    # Get room/player/game info needed for names - optimize later if needed
    all_room_db_ids = list(room_id_to_uuid.keys())
    all_subs = session.query(UserRoomSubscription).filter(UserRoomSubscription.room_id.in_(all_room_db_ids)).all()
    alias_map = {sub.room_id: sub.alias for sub in all_subs} # room_db_id -> alias

    all_rooms_full = session.query(TrackedRoom).filter(TrackedRoom.id.in_(all_room_db_ids)).all()
    player_map_by_room = {r.id: {p['slot_id']: p['name'] for p in json.loads(r.cached_players_json or '[]')} for r in all_rooms_full} # room_db_id -> {slot_id: name}
    game_map_by_room = {r.id: {p['slot_id']: p['game'] for p in json.loads(r.cached_players_json or '[]')} for r in all_rooms_full} # room_db_id -> {slot_id: game}
    checksum_map_by_room = {r.id: json.loads(r.game_checksums_json or '{}') for r in all_rooms_full} # room_db_id -> {game: checksum}
    uuid_to_db_id = {v: k for k, v in room_id_to_uuid.items()}


    for hint in all_relevant_hints:
        room_db_id_for_hint = uuid_to_db_id.get(hint.room_id)
        if not room_db_id_for_hint: continue # Should not happen

        # Check if this hint involves a slot the user is tracking
        is_item_owner_tracked = (room_db_id_for_hint, hint.item_owner_id) in user_tracked_tuples
        is_location_owner_tracked = (room_db_id_for_hint, hint.location_owner_id) in user_tracked_tuples

        if not (is_item_owner_tracked or is_location_owner_tracked):
            continue # Skip hints not involving user's tracked slots

        # Get names using cached data
        player_map = player_map_by_room.get(room_db_id_for_hint, {})
        game_map = game_map_by_room.get(room_db_id_for_hint, {})
        checksum_map = checksum_map_by_room.get(room_db_id_for_hint, {})

        item_owner_name = player_map.get(hint.item_owner_id, f"Player {hint.item_owner_id}")
        location_owner_name = player_map.get(hint.location_owner_id, f"Player {hint.location_owner_id}")

        item_owner_game = game_map.get(hint.item_owner_id)
        location_owner_game = game_map.get(hint.location_owner_id)

        item_checksum = checksum_map.get(item_owner_game) if item_owner_game else None
        location_checksum = checksum_map.get(location_owner_game) if location_owner_game else None

        item_name = session.query(DatapackageCache.entity_name).filter_by(
            game=item_owner_game, checksum=item_checksum, entity_type='item', entity_id=hint.item_id
        ).scalar() or f"Item ID {hint.item_id}"

        location_name = session.query(DatapackageCache.entity_name).filter_by(
            game=location_owner_game, checksum=location_checksum, entity_type='location', entity_id=hint.location_id
        ).scalar() or f"Location ID {hint.location_id}"


        hint_data = {
            "id": hint.id, # Include DB ID for potential future use
            "room_db_id": room_db_id_for_hint,
            "room_alias": alias_map.get(room_db_id_for_hint, "Unknown Room"),
            "item_owner_id": hint.item_owner_id,
            "item_owner_name": item_owner_name,
            "location_owner_id": hint.location_owner_id,
            "location_owner_name": location_owner_name,
            "item_name": item_name,
            "location_name": location_name,
            "is_found": getattr(hint, 'is_found', False), # Default to False if column doesn't exist yet
            # Use hint.id as a proxy for timestamp if column doesn't exist
            "timestamp": getattr(hint, 'timestamp', datetime.fromtimestamp(hint.id / 1000.0, tz=timezone.utc)).replace(tzinfo=timezone.utc).isoformat() if hasattr(hint, 'timestamp') else str(hint.id) # Fallback to ID if no timestamp
        }

        if is_item_owner_tracked:
            hints_for_you.append(hint_data)
        elif is_location_owner_tracked: # Only add to 'by_you' if not already 'for_you'
            hints_by_you.append(hint_data)

    # We might need to sort again if using hint.id as fallback timestamp wasn't reliable
    # Or if the original query order wasn't perfect time order
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
    
    # --- NEW: Get include_found param ---
    include_found_str = request.args.get('include_found', 'false')
    include_found = include_found_str.lower() in ['true', '1', 't', 'yes']
    # --- END NEW ---
    
    session = Session()
    try:
        # --- MODIFIED: Pass param ---
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
    
    # --- NEW: Get include_found param ---
    include_found_str = request.args.get('include_found', 'false')
    include_found = include_found_str.lower() in ['true', '1', 't', 'yes']
    # --- END NEW ---
    
    session = Session()
    try:
        # Basic check: Does user subscribe to this room at all?
        sub_exists = session.query(UserRoomSubscription.user_id).filter_by(
            user_id=current_user.id, room_id=room_db_id
        ).limit(1).scalar() is not None
        if not sub_exists:
            return jsonify({'error': 'Subscription not found'}), 404

        # --- MODIFIED: Pass param ---
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