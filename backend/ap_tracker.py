# app.py
# A single-file, multi-device backend for tracking Archipelago rooms.
# This script runs a Flask API server and a background polling service in separate threads.

import os
import json
import time
import asyncio
import aiohttp
import requests
import websockets
from threading import Thread, local
from datetime import datetime, timezone, timedelta
from functools import wraps
import psutil

# --- Core Dependencies ---
from flask import Flask, request, jsonify
from waitress import serve
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime, UniqueConstraint, event, or_
from sqlalchemy.orm import relationship, sessionmaker, declarative_base, scoped_session
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, IntegrityError
from requests.adapters import HTTPAdapter
from urllib.parse import urlparse
from urllib3.util.retry import Retry

# --- Firebase for Push Notifications ---
import firebase_admin
from firebase_admin import credentials, messaging

# --- Environment Variable Loading ---
from dotenv import load_dotenv

# ==============================================================================
# 1. CONFIGURATION & INITIALIZATION
# ==============================================================================
process = psutil.Process(os.getpid())
process.cpu_percent(interval=None)

# --- Load environment variables from .env file ---
load_dotenv()

# --- Constants ---
DATABASE_FILE = "ap_tracker.db"
ARCHIPELAGO_HOST = "archipelago.gg"
POLLING_INTERVAL_SECONDS = 60
SUPERVISOR_INTERVAL_SECONDS = 30
FIREBASE_KEY_FILE = "service-account-key.json"

# --- Create a single, robust, global HTTP session for Firebase to use ---
retry_strategy = Retry(
    total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
)
adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retry_strategy)
firebase_http_session = requests.Session()
firebase_http_session.mount("https://", adapter)

# --- Database Setup ---
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

engine = create_engine(
    f"sqlite:///{DATABASE_FILE}",
    connect_args={"check_same_thread": False, "timeout": 30}
)
Base = declarative_base()
session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)

# --- Firebase Setup (Lazy Initialization) ---
_firebase_app = None
def get_firebase_app():
    global _firebase_app
    if _firebase_app is None:
        try:
            cred = credentials.Certificate(FIREBASE_KEY_FILE)
            _firebase_app = firebase_admin.initialize_app(cred, {'http_client': firebase_http_session})
            print("[FIREBASE] Firebase initialized successfully using global HTTP session.")
        except Exception as e:
            print(f"[FIREBASE] !!! FIREBASE ERROR: Could not initialize. Error: {e}")
    return _firebase_app

# --- Thread-local Storage for Async HTTP Client ---
thread_local_data = local()
def get_aiohttp_session():
    if not hasattr(thread_local_data, "aiohttp_session"):
        thread_local_data.aiohttp_session = aiohttp.ClientSession()
    return thread_local_data.aiohttp_session

def log_resource_usage():
    """Logs the current CPU and Memory usage of this script."""
    # The global 'process' variable is already initialized.
    
    # Get CPU usage since the LAST time this function was called (non-blocking)
    cpu_usage = process.cpu_percent(interval=None)
    
    # Get memory usage and convert it to megabytes (MB)
    memory_info = process.memory_info()
    memory_mb = memory_info.rss / (1024 * 1024)
    
    print(f"[RESOURCES] CPU: {cpu_usage:.2f}% | Memory: {memory_mb:.2f} MB")

# ==============================================================================
# 2. DATABASE MODELS
# ==============================================================================

class Device(Base):
    __tablename__ = 'devices'
    id = Column(Integer, primary_key=True)
    fcm_token = Column(String, nullable=False, unique=True, index=True)

class TrackedRoom(Base):
    __tablename__ = 'tracked_rooms'
    id = Column(Integer, primary_key=True)
    room_id = Column(String, nullable=False, unique=True)
    alias = Column(String, nullable=False)
    hostname = Column(String, default="archipelago.gg")
    tracker_id = Column(String)
    icon_name = Column(String, default="default_icon")
    game_checksums_json = Column(String, default='{}')
    slots = relationship("TrackedSlot", back_populates="room", cascade="all, delete-orphan")
    cached_full_address = Column(String, default="archipelago.gg")
    cached_total_slots = Column(Integer, default=0)
    last_api_check = Column(DateTime)
    cached_players_json = Column(String, default='[]')

class TrackedSlot(Base):
    __tablename__ = 'tracked_slots'
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey('tracked_rooms.id'), nullable=False)
    slot_id = Column(Integer, nullable=False)
    room = relationship("TrackedRoom", back_populates="slots")
    __table_args__ = (UniqueConstraint('room_id', 'slot_id', name='_room_slot_uc'),)

class DatapackageCache(Base):
    __tablename__ = 'datapackage_cache'
    id = Column(Integer, primary_key=True)
    game = Column(String, nullable=False, index=True)
    checksum = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=False)
    entity_name = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint('game', 'checksum', 'entity_type', 'entity_id', name='_game_checksum_entity_uc'),)

class NotifiedItem(Base):
    __tablename__ = 'notified_items'
    id = Column(Integer, primary_key=True)
    room_id = Column(String, nullable=False, index=True)
    receiving_slot_id = Column(Integer, nullable=False)
    item_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('room_id', 'receiving_slot_id', 'item_id', 'location_id', name='_item_event_uc'),)

class NotifiedHint(Base):
    __tablename__ = 'notified_hints'
    id = Column(Integer, primary_key=True)
    room_id = Column(String, nullable=False, index=True)
    item_owner_id = Column(Integer, nullable=False)
    location_owner_id = Column(Integer, nullable=False)
    item_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint('room_id', 'item_id', 'location_id', 'item_owner_id', 'location_owner_id', name='_hint_event_uc'),)

# ==============================================================================
# 3. FLASK API
# ==============================================================================

app = Flask(__name__)

# --- Logging Middleware ---
@app.before_request
def log_request_info():
    """Logs incoming request details, including the payload."""
    # This logging runs in all environments
    payload = request.get_json(silent=True)
    log_line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] API Call: {request.method} {request.path}"
    if payload:
        log_line += f" | Payload: {json.dumps(payload)}"
    print(log_line)

@app.after_request
def log_response_info(response):
    """Logs outgoing response details, but only in the development environment."""
    # Check the environment variable loaded from the .env file
    if os.getenv("ENVIRONMENT") == "development":
        try:
            data = response.get_data(as_text=True)
            log_line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] API Response: {response.status_code} | Body: {data}"
            print(log_line)
        except Exception:
            pass # Avoid crashing on non-json or large responses
    return response

# --- Error Handling ---
def handle_db_errors(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except OperationalError as e:
            if "database is locked" in str(e).lower():
                return jsonify({'error': 'The database is busy. Please try again in a moment.'}), 503
            else: raise
    return decorated_function

# --- API Endpoints ---
@app.route('/devices', methods=['POST'])
@handle_db_errors
def register_device():
    data = request.json
    if not data or 'token' not in data: return jsonify({'error': 'Missing device token'}), 400
    token = data['token']
    session = Session()
    if not session.query(Device).filter_by(fcm_token=token).first():
        session.add(Device(fcm_token=token))
        session.commit()
    return jsonify({'message': 'Device registered.'}), 201

@app.route('/rooms', methods=['GET'])
@handle_db_errors
def get_tracked_rooms():
    session = Session()
    rooms = session.query(TrackedRoom).all()
    rooms_data = []
    cache_expiry_duration = timedelta(hours=1)

    for room in rooms:
        now = datetime.now(timezone.utc)
        is_cache_stale = not room.last_api_check or (now - room.last_api_check.replace(tzinfo=timezone.utc) > cache_expiry_duration)

        if is_cache_stale:
            try:
                url = f"https://{room.hostname}/api/room_status/{room.room_id}"
                response = requests.get(url, timeout=5)
                if response.ok:
                    data = response.json()
                    room.cached_total_slots = len(data.get('players', []))
                    room.cached_full_address = f"{room.hostname}:{data['last_port']}" if 'last_port' in data else room.hostname
                    room.last_api_check = datetime.utcnow()
                    session.commit()
            except requests.RequestException as e:
                print(f"[CACHE_ERROR] Could not refresh room '{room.alias}'. Using stale data. Error: {e}")

        rooms_data.append({
            'id': room.id,
            'room_id': room.room_id,
            'alias': room.alias,
            'tracked_slots_count': len(room.slots),
            'host': room.cached_full_address,
            'total_slots_count': room.cached_total_slots,
            'icon_name': room.icon_name
        })
        
    return jsonify(rooms_data)

@app.route('/rooms', methods=['POST'])
@handle_db_errors
def add_tracked_room():
    data = request.json
    if not data or 'room_url' not in data or 'alias' not in data: 
        return jsonify({'error': 'Missing room_url or alias'}), 400
    
    try:
        parsed_url = urlparse(data['room_url'])
        hostname = parsed_url.netloc
        room_id = os.path.basename(parsed_url.path)

        if not hostname or not room_id:
            return jsonify({'error': 'Invalid Room URL format.'}), 400
    except Exception:
        return jsonify({'error': 'Could not parse Room URL.'}), 400

    try:
        url = f"https://{hostname}/api/room_status/{room_id}"
        response = requests.get(url, timeout=10)
        if response.status_code >= 400: 
            return jsonify({'error': f'Invalid room (status {response.status_code}).'}), 400
        
        api_data = response.json()
        players_raw = api_data.get('players', [])
        
        player_list = [{'slot_id': i + 1, 'name': p[0], 'game': p[1]} for i, p in enumerate(players_raw)]
        players_json = json.dumps(player_list)
        
        total_slots = len(players_raw)
        full_address = f"{hostname}:{api_data['last_port']}" if 'last_port' in api_data else hostname

    except requests.RequestException as e: 
        return jsonify({'error': f'Could not validate room: {e}'}), 502

    session = Session()
    if session.query(TrackedRoom).filter_by(room_id=room_id).first(): 
        return jsonify({'error': 'Room already tracked'}), 409

    new_room = TrackedRoom(
        room_id=room_id,
        hostname=hostname,
        alias=data['alias'],
        icon_name=data.get('icon_name', 'default_icon'),
        cached_full_address=full_address,
        cached_total_slots=total_slots,
        cached_players_json=players_json,
        last_api_check=datetime.utcnow()
    )
    session.add(new_room)
    session.commit()
    
    return jsonify({'message': f"Room '{new_room.alias}' added.", 'id': new_room.id}), 201

@app.route('/rooms/<int:room_db_id>', methods=['PUT'])
@handle_db_errors
def update_tracked_room(room_db_id):
    data = request.json
    if not data or 'alias' not in data or 'icon_name' not in data:
        return jsonify({'error': 'Missing alias or icon_name'}), 400

    session = Session()
    room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
    if not room:
        return jsonify({'error': 'Room not found'}), 404

    room.alias = data['alias']
    room.icon_name = data['icon_name']
    session.commit()
    return jsonify({'message': 'Room updated.'})

@app.route('/rooms/<int:room_db_id>', methods=['DELETE'])
@handle_db_errors
def delete_tracked_room(room_db_id):
    session = Session()
    room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
    if not room: return jsonify({'error': 'Room not found'}), 404
    session.delete(room)
    session.commit()
    return jsonify({'message': f"Room '{room.alias}' deleted."})

@app.route('/rooms/<int:room_db_id>/players', methods=['GET'])
@handle_db_errors
def get_room_players(room_db_id):
    session = Session()
    room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
    if not room: 
        return jsonify({'error': 'Room not found'}), 404

    # 1. Get the set of currently tracked slot IDs from our database. This is fast.
    tracked_slot_ids = {slot.slot_id for slot in room.slots}
    
    # 2. Load the cached player list from the database. This is also fast.
    player_list = json.loads(room.cached_players_json)

    # 3. Add the 'is_tracked' status to each player in the list.
    for player in player_list:
        player['is_tracked'] = player['slot_id'] in tracked_slot_ids
    
    # No API call needed!
    return jsonify(player_list)

@app.route('/rooms/<int:room_db_id>/slots', methods=['PUT'])
@handle_db_errors
def update_tracked_slots(room_db_id):
    data = request.json
    if 'tracked_slot_ids' not in data: return jsonify({'error': 'Missing tracked_slot_ids'}), 400
    
    session = Session()
    room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
    if not room: return jsonify({'error': 'Room not found'}), 404

    current_tracked_ids = {slot.slot_id for slot in room.slots}
    requested_ids = set(data.get('tracked_slot_ids', []))
    newly_added_slots = requested_ids - current_tracked_ids

    if newly_added_slots and room.tracker_id:
        print(f"[API] Pre-filling history for {len(newly_added_slots)} new slot(s) in room '{room.alias}'.")
        try:
            # Fetch the complete tracker data once
            url = f"https://{room.hostname}/api/tracker/{room.tracker_id}"            
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            tracker_data = response.json()

            # --- PRE-FILL ITEM HISTORY ---
            existing_items_in_db = session.query(NotifiedItem.receiving_slot_id, NotifiedItem.item_id, NotifiedItem.location_id).filter(
                NotifiedItem.room_id == room.room_id, NotifiedItem.receiving_slot_id.in_(newly_added_slots)
            ).all()
            existing_item_set = set(existing_items_in_db)
            items_to_add, unique_items_from_api = [], set()

            for player_data in tracker_data.get('player_items_received', []):
                receiving_slot_id = player_data.get('player')
                if receiving_slot_id in newly_added_slots:
                    for item_id, loc_id, _, _ in player_data.get('items', []):
                        item_tuple = (receiving_slot_id, item_id, loc_id)
                        if item_tuple not in existing_item_set and item_tuple not in unique_items_from_api:
                            items_to_add.append(NotifiedItem(room_id=room.room_id, receiving_slot_id=receiving_slot_id, item_id=item_id, location_id=loc_id))
                            unique_items_from_api.add(item_tuple)
            
            if items_to_add:
                session.bulk_save_objects(items_to_add)
                print(f"[API] Silently added {len(items_to_add)} historical items.")

            # --- PRE-FILL HINT HISTORY ---
            existing_hints_in_db = session.query(NotifiedHint.item_owner_id, NotifiedHint.location_owner_id, NotifiedHint.item_id, NotifiedHint.location_id).filter(
                NotifiedHint.room_id == room.room_id, or_(NotifiedHint.item_owner_id.in_(newly_added_slots), NotifiedHint.location_owner_id.in_(newly_added_slots))
            ).all()
            existing_hint_set = set(existing_hints_in_db)
            hints_to_add, unique_hints_from_api = [], set()

            for p_hints in tracker_data.get('hints', []):
                for hint_data in p_hints.get('hints', []):
                    io_id, lo_id, loc_id, item_id, *_ = hint_data
                    if io_id in newly_added_slots or lo_id in newly_added_slots:
                        hint_tuple = (io_id, lo_id, item_id, loc_id)
                        if hint_tuple not in existing_hint_set and hint_tuple not in unique_hints_from_api:
                            hints_to_add.append(NotifiedHint(room_id=room.room_id, item_owner_id=io_id, location_owner_id=lo_id, item_id=item_id, location_id=loc_id))
                            unique_hints_from_api.add(hint_tuple)
            
            if hints_to_add:
                session.bulk_save_objects(hints_to_add)
                print(f"[API] Silently added {len(hints_to_add)} historical hints.")

        except (requests.RequestException, IntegrityError) as e:
            session.rollback()
            print(f"[API_ERROR] Could not pre-fill history for new slots in '{room.alias}': {e}")
        except Exception as e:
            session.rollback()
            print(f"[API_ERROR] A general error occurred during history pre-fill: {e}")

    # Update the tracked slots in the database
    session.query(TrackedSlot).filter_by(room_id=room.id).delete()
    for slot_id in requested_ids:
        if isinstance(slot_id, int) and slot_id > 0: 
            session.add(TrackedSlot(room_id=room.id, slot_id=slot_id))
    
    session.commit()
    return jsonify({'message': 'Tracked slots updated.'})

@app.route('/rooms/<int:room_db_id>/history/items', methods=['GET'])
@handle_db_errors
def get_item_history(room_db_id):
    session = Session()
    room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
    if not room: return jsonify({'error': 'Room not found'}), 404

    game_checksums = json.loads(room.game_checksums_json)
    tracked_slot_ids = {slot.slot_id for slot in room.slots}
    if not tracked_slot_ids: return jsonify([])

    # --- THIS IS THE UPDATED QUERY LOGIC ---
    query = session.query(NotifiedItem).filter(
        NotifiedItem.room_id == room.room_id,
        NotifiedItem.receiving_slot_id.in_(tracked_slot_ids)
    )

    # Check for the 'since' parameter
    since_timestamp = request.args.get('since')
    if since_timestamp:
        try:
            # Parse the ISO 8601 timestamp from the app
            since_dt = datetime.fromisoformat(since_timestamp.replace('Z', '+00:00'))
            query = query.filter(NotifiedItem.timestamp > since_dt)
        except (ValueError, TypeError):
            pass # Ignore invalid timestamps

    items = query.order_by(NotifiedItem.id.desc()).limit(100).all()
    # --- END OF QUERY LOGIC UPDATE ---

    try:
        url = f"https://{ARCHIPELAGO_HOST}/api/room_status/{room.room_id}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        players = response.json().get('players', [])
        name_map = {i + 1: p[0] for i, p in enumerate(players)}
        game_map = {i + 1: p[1] for i, p in enumerate(players)}
    except requests.RequestException: name_map, game_map = {}, {}

    history = []
    for item in items:
        receiver_name = name_map.get(item.receiving_slot_id, f"P{item.receiving_slot_id}")
        receiver_game = game_map.get(item.receiving_slot_id, "Unknown")
        game_checksum = game_checksums.get(receiver_game)

        item_name = session.query(DatapackageCache.entity_name).filter_by(game=receiver_game, checksum=game_checksum, entity_type='item', entity_id=item.item_id).scalar() or f"ID {item.item_id}"

        history.append({
            "message": f"{receiver_name} received: {item_name}",
            "timestamp": item.timestamp.replace(tzinfo=timezone.utc).isoformat(),
            "tracker_id": room.tracker_id,
            "slot_id": item.receiving_slot_id,
            "icon_name": room.icon_name
        })

    return jsonify(history)


@app.route('/history/items', methods=['GET'])
@handle_db_errors
def get_global_item_history():
    session = Session()
    all_rooms = session.query(TrackedRoom).all()
    if not all_rooms: return jsonify([])

    filters = []
    room_data_map = {}
    for room in all_rooms:
        try:
            tracked_slot_ids = {slot.slot_id for slot in room.slots}
            if tracked_slot_ids:
                filters.append(
                    (NotifiedItem.room_id == room.room_id) &
                    (NotifiedItem.receiving_slot_id.in_(tracked_slot_ids))
                )
                room_data_map[room.room_id] = {
                    'db_id': room.id,
                    'game_checksums': json.loads(room.game_checksums_json),
                    'tracker_id': room.tracker_id,
                    'icon_name': room.icon_name
                }
        except Exception as e:
            print(f"[ERROR] Skipping room '{room.alias}' ({room.room_id}) due to a data error: {e}")
            continue

    if not filters: return jsonify([])

    query = session.query(NotifiedItem).filter(or_(*filters))

    since_timestamp = request.args.get('since')
    if since_timestamp:
        try:
            since_dt = datetime.fromisoformat(since_timestamp.replace('Z', '+00:00'))
            query = query.filter(NotifiedItem.timestamp > since_dt)
        except (ValueError, TypeError): pass

    # --- THE FIX: Remove the .limit(200) from this line ---
    items = query.order_by(NotifiedItem.id.desc()).all()

    if not items: return jsonify([])

    room_ids_in_history = {item.room_id for item in items}
    for room_id in room_ids_in_history:
        try:
            url = f"https://{ARCHIPELAGO_HOST}/api/room_status/{room_id}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            players = response.json().get('players', [])
            if room_id in room_data_map:
                room_data_map[room_id]['name_map'] = {i + 1: p[0] for i, p in enumerate(players)}
                room_data_map[room_id]['game_map'] = {i + 1: p[1] for i, p in enumerate(players)}
        except requests.RequestException:
            if room_id in room_data_map:
                room_data_map[room_id]['name_map'] = {}
                room_data_map[room_id]['game_map'] = {}

    history = []
    for item in items:
        room_data = room_data_map.get(item.room_id)
        if not room_data: continue

        name_map = room_data.get('name_map', {})
        game_map = room_data.get('game_map', {})
        game_checksums = room_data.get('game_checksums', {})
        tracker_id = room_data.get('tracker_id')
        icon_name = room_data.get('icon_name')
        db_id = room_data.get('db_id')

        receiver_name = name_map.get(item.receiving_slot_id, f"P{item.receiving_slot_id}")
        receiver_game = game_map.get(item.receiving_slot_id, "Unknown")
        game_checksum = game_checksums.get(receiver_game)

        item_name = session.query(DatapackageCache.entity_name).filter_by(
            game=receiver_game,
            checksum=game_checksum,
            entity_type='item',
            entity_id=item.item_id
        ).scalar() or f"ID {item.item_id}"

        history.append({
            "message": f"{receiver_name} received: {item_name}",
            "timestamp": item.timestamp.replace(tzinfo=timezone.utc).isoformat(),
            "tracker_id": tracker_id,
            "slot_id": item.receiving_slot_id,
            "icon_name": icon_name,
            'db_id': db_id
        })

    return jsonify(history)

@app.teardown_appcontext
def shutdown_session(exception=None):
    Session.remove()

# ==============================================================================
# 4. BACKGROUND POLLER
# ==============================================================================
async def send_push_notifications(notifications, device_tokens):
    firebase_app = get_firebase_app()
    if not firebase_app or not notifications or not device_tokens: return

    messages = []
    for content in notifications:
        for token in device_tokens:
            android_config = messaging.AndroidConfig(priority='high')
            messages.append(messaging.Message(
                notification=messaging.Notification(title=content['title'], body=content['body']),
                token=token, android=android_config
            ))

    if not messages:
        return

    loop = asyncio.get_running_loop()
    # Process messages in chunks of 10
    for i in range(0, len(messages), 10):
        chunk = messages[i:i + 10]
        try:
            print(f"[FCM] Sending a chunk of {len(chunk)} messages...")
            response = await loop.run_in_executor(None, lambda: messaging.send_each(chunk))

            unregistered_tokens = []
            for idx, res in enumerate(response.responses):
                message_title = chunk[idx].notification.title
                if res.success:
                    print(f"  - SUCCESS: '{message_title}'")
                else:
                    error_code = res.exception.code if hasattr(res.exception, 'code') else "UNKNOWN"
                    error_message = str(res.exception)
                    print(f"  - FAILED: '{message_title}'. Code: {error_code}, Error: {error_message}")

                    # --- THE FIX: Check for both UNREGISTERED and NOT_FOUND ---
                    if error_code in ['UNREGISTERED', 'NOT_FOUND']:
                        unregistered_tokens.append(chunk[idx].token)

            if unregistered_tokens:
                print(f"[FCM] Found {len(unregistered_tokens)} invalid devices. Removing from DB.")
                session = Session()
                session.query(Device).filter(Device.fcm_token.in_(unregistered_tokens)).delete(synchronize_session=False)
                session.commit()
                Session.remove()

        except Exception as e:
            print(f"[FCM] A critical error occurred while sending a chunk: {e}")

        if i + 10 < len(messages):
            print("[FCM] Waiting 1 second before next chunk...")
            await asyncio.sleep(1)

async def fetch_json(url):
    session = get_aiohttp_session()
    try:
        async with session.get(url, timeout=15) as response:
            response.raise_for_status()
            return await response.json()
    except Exception as e: return None

async def poll_room_instance(room_info):
    session = Session()
    try:
        room_id, tracker_id, room_alias, hostname = room_info['room_id'], room_info['tracker_id'], room_info['alias'], room_info['hostname']
        timestamp = datetime.now().strftime('%H:%M:%S')
        db_room = session.query(TrackedRoom).filter(TrackedRoom.room_id == room_id).first()
        if not db_room: return

        game_checksums = json.loads(db_room.game_checksums_json)
        all_tracked_slots = {slot.slot_id for slot in db_room.slots}
        if not all_tracked_slots: return

        tracker_data = await fetch_json(f"https://{hostname}/api/tracker/{tracker_id}")
        if not tracker_data: return

        room_status_data = await fetch_json(f"https://{hostname}/api/room_status/{room_id}")
        players = room_status_data.get('players', []) if room_status_data else []
        name_map = {i + 1: p[0] for i, p in enumerate(players)}
        game_map = {i + 1: p[1] for i, p in enumerate(players)}
        device_tokens = [d.fcm_token for d in session.query(Device.fcm_token).all()]
        if not device_tokens: return
        
        unique_notification_contents = set()
        
        # --- FINISHED PLAYER LOGIC (UNCHANGED) ---
        finished_player_ids = set()
        player_statuses_raw = tracker_data.get('player_status', {})
        if isinstance(player_statuses_raw, dict):
            for slot_id_str, status_code in player_statuses_raw.items():
                if int(slot_id_str) in all_tracked_slots and status_code == 30: finished_player_ids.add(int(slot_id_str))
        elif isinstance(player_statuses_raw, list):
            for status_info in player_statuses_raw:
                slot_id, status_code = -1, -1
                if isinstance(status_info, dict): slot_id, status_code = status_info.get('player', -1), status_info.get('status', -1)
                elif isinstance(status_info, (list, tuple)) and len(status_info) >= 2: slot_id, status_code, *_ = status_info
                if slot_id != -1 and int(slot_id) in all_tracked_slots and status_code == 30: finished_player_ids.add(int(slot_id))

        if finished_player_ids:
            for slot_id in finished_player_ids:
                name = name_map.get(slot_id, f"P{slot_id}")
                unique_notification_contents.add((f"🏁 {name} Finished!", f"Player has finished in room '{room_alias}'"))
                if slot := session.query(TrackedSlot).filter_by(room_id=db_room.id, slot_id=slot_id).first(): session.delete(slot)
            session.commit()
        
        active_tracked_slots = all_tracked_slots - finished_player_ids
        if not active_tracked_slots:
            if unique_notification_contents:
                notifications_to_send = [{'title': t, 'body': b} for t, b in unique_notification_contents]
                print(f"[{timestamp}][{room_alias}] Found {len(notifications_to_send)} unique events. Sending notifications to {len(device_tokens)} devices.")
                for n in notifications_to_send: print(f"  - {n['title']}: {n['body']}")
                await send_push_notifications(notifications_to_send, device_tokens)
            return
        
        # --- MAIN NOTIFICATION LOGIC ---
        existing_items = {(i.receiving_slot_id, i.item_id, i.location_id) for i in session.query(NotifiedItem).filter_by(room_id=room_id)}
        existing_hints_tuples = {(h.item_owner_id, h.location_owner_id, h.item_id, h.location_id) for h in session.query(NotifiedHint).filter_by(room_id=room_id)}
        newly_notified_items, newly_notified_hints = [], []

        # Get a set of our tracked players' hinted items to check against received items.
        our_active_hints = {(h.item_id, h.location_id): h.item_owner_id for h in session.query(NotifiedHint).filter(
            NotifiedHint.room_id == room_id, NotifiedHint.item_owner_id.in_(active_tracked_slots)
        )}

        # --- 1. PROCESS RECEIVED ITEMS (Requirement #2 and #3) ---
        for p_items in tracker_data.get('player_items_received', []):
            rid = p_items.get('player') # receiver_id
            for item_id, loc_id, _, flags in p_items.get('items', []):
                if (rid, item_id, loc_id) in existing_items: continue

                item_location_tuple = (item_id, loc_id)
                is_our_hinted_item_found = item_location_tuple in our_active_hints
                
                # --- Requirement #2: Our hinted item was found (ANY rarity) ---
                if is_our_hinted_item_found:
                    owner_id = our_active_hints[item_location_tuple]
                    owner_game = game_map.get(owner_id, "Unknown")
                    owner_checksum = game_checksums.get(owner_game)
                    item_name = session.query(DatapackageCache.entity_name).filter_by(game=owner_game, checksum=owner_checksum, entity_type='item', entity_id=item_id).scalar() or f"ID {item_id}"
                    
                    title = f"🔍 {item_name}"
                    body = f"Found by {name_map.get(rid, f'P{rid}')} in '{room_alias}'"
                    unique_notification_contents.add((title, body))
                    newly_notified_items.append(NotifiedItem(room_id=room_id, receiving_slot_id=rid, item_id=item_id, location_id=loc_id))
                    existing_items.add((rid, item_id, loc_id))

                # --- Requirement #3: A tracked slot received a PROGRESSION item ---
                elif bool(flags & 1) and rid in active_tracked_slots:
                    receiver_game = game_map.get(rid, "Unknown")
                    receiver_checksum = game_checksums.get(receiver_game)
                    item_name = session.query(DatapackageCache.entity_name).filter_by(game=receiver_game, checksum=receiver_checksum, entity_type='item', entity_id=item_id).scalar() or f"ID {item_id}"
                    
                    title = f"✨ {item_name}"
                    body = f"Received by {name_map.get(rid, f'P{rid}')} in '{room_alias}'"
                    unique_notification_contents.add((title, body))
                    newly_notified_items.append(NotifiedItem(room_id=room_id, receiving_slot_id=rid, item_id=item_id, location_id=loc_id))
                    existing_items.add((rid, item_id, loc_id))

        # --- 2. PROCESS NEW HINTS (Requirement #1) ---
        for p_hints in tracker_data.get('hints', []):
            for hint_data in p_hints.get('hints', []):
                io_id, lo_id, loc_id, item_id, *_ = hint_data
                hint_tuple = (io_id, lo_id, item_id, loc_id)
                if hint_tuple in existing_hints_tuples: continue
                
                is_for_us = io_id in active_tracked_slots
                is_at_our_location = lo_id in active_tracked_slots
                
                if is_for_us or is_at_our_location:
                    io_game, lo_game = game_map.get(io_id, "Unknown"), game_map.get(lo_id, "Unknown")
                    io_checksum, lo_checksum = game_checksums.get(io_game), game_checksums.get(lo_game)
                    item_name = session.query(DatapackageCache.entity_name).filter_by(game=io_game, checksum=io_checksum, entity_type='item', entity_id=item_id).scalar() or f"ID {item_id}"
                    loc_name = session.query(DatapackageCache.entity_name).filter_by(game=lo_game, checksum=lo_checksum, entity_type='location', entity_id=loc_id).scalar() or f"ID {loc_id}"
                    
                    # A hint for one of our items.
                    if is_for_us:
                        title = f"[{room_alias}] Hint for your item!"
                        body = f"Your '{item_name}' is at {name_map.get(lo_id)}'s location: '{loc_name}'."
                        unique_notification_contents.add((title, body))
                    
                    # --- Requirement #1: A hint for an item AT one of our locations ---
                    if is_at_our_location and io_id != lo_id:
                        our_player_name = name_map.get(lo_id, f'P{lo_id}')
                        hinter_name = name_map.get(io_id, f'P{io_id}')
                        title = f"🔍 New Hint for {our_player_name} in '{room_alias}'"
                        body = f"{hinter_name}'s '{item_name}' is at your {lo_game}: '{loc_name}'"
                        unique_notification_contents.add((title, body))

                    newly_notified_hints.append(NotifiedHint(room_id=room_id, item_owner_id=io_id, location_owner_id=lo_id, item_id=item_id, location_id=loc_id))
                    existing_hints_tuples.add(hint_tuple)

        if newly_notified_items: session.bulk_save_objects(newly_notified_items)
        if newly_notified_hints: session.bulk_save_objects(newly_notified_hints)
        if newly_notified_items or newly_notified_hints: session.commit()

        if unique_notification_contents:
            notifications_to_send = [{'title': t, 'body': b} for t, b in unique_notification_contents]
            print(f"[{timestamp}][{room_alias}] Found {len(notifications_to_send)} unique events. Sending notifications to {len(device_tokens)} devices.")
            for n in notifications_to_send: print(f"  - {n['title']}: {n['body']}")
            await send_push_notifications(notifications_to_send, device_tokens)
        
    finally:
        Session.remove()

async def setup_and_cache_datapackage(room_id, hostname, session):
    try:
        room_info = await fetch_json(f"https://{hostname}/api/room_status/{room_id}")        
        if not room_info: return None
        tracker_id, port = room_info.get('tracker'), room_info.get('last_port')
        if not tracker_id or not port: return None
        uri = f"wss://{hostname}:{port}"
        checksums = {}
        try:
            async with websockets.connect(uri, open_timeout=10) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                checksums = json.loads(msg)[0].get('datapackage_checksums', {})
        except Exception: checksums = room_info.get('datapackage_checksums', {})
        if not checksums: return tracker_id

        for game, checksum in checksums.items():
            if session.query(DatapackageCache).filter_by(game=game, checksum=checksum).first():
                print(f"[SETUP][{room_id}] Datapackage for {game} (checksum: {checksum[:8]}...) already cached.")
                continue

            print(f"[SETUP][{room_id}] Caching new datapackage for {game} (checksum: {checksum[:8]}...)")
            game_data = await fetch_json(f"https://{hostname}/api/datapackage/{checksum}")
            if not game_data: continue
            actual_data = game_data['games'][game] if 'games' in game_data and game in game_data['games'] else game_data

            unique_entries = {}
            for n, eid in actual_data.get('item_name_to_id', {}).items():
                if (game, checksum, 'item', eid) not in unique_entries: unique_entries[(game, checksum, 'item', eid)] = DatapackageCache(game=game, checksum=checksum, entity_type='item', entity_id=eid, entity_name=n)
            for n, eid in actual_data.get('location_name_to_id', {}).items():
                if (game, checksum, 'location', eid) not in unique_entries: unique_entries[(game, checksum, 'location', eid)] = DatapackageCache(game=game, checksum=checksum, entity_type='location', entity_id=eid, entity_name=n)
            if unique_entries: session.bulk_save_objects(list(unique_entries.values()))

        if room := session.query(TrackedRoom).filter_by(room_id=room_id).first():
            room.game_checksums_json = json.dumps(checksums)
        session.commit()
        return tracker_id
    except Exception as e:
        print(f"[SETUP][{room_id}] Error during setup: {e}")
        session.rollback()
        return None

async def poller_supervisor():
    print("[POLLER] Background polling service starting...")
    running_tasks = {} 

    while True:
        session = Session()
        try:
            log_resource_usage()

            rooms_in_db = session.query(TrackedRoom).all()
            current_rooms_data = {
                r.room_id: {'tracker_id': r.tracker_id, 'alias': r.alias, 'room_id': r.room_id, 'hostname': r.hostname} 
                for r in rooms_in_db
            }

            for room_id, new_data in current_rooms_data.items():
                task_info = running_tasks.get(room_id)

                if not task_info or task_info['data'] != new_data:
                    if task_info:
                        print(f"[SUPERVISOR] Data for room '{task_info['data']['alias']}' has changed. Restarting poller.")
                        task_info['task'].cancel()
                    
                    if not new_data['tracker_id']:
                        print(f"[SUPERVISOR] First time seeing room {room_id}. Performing setup...")
                        tracker_id = await setup_and_cache_datapackage(room_id, new_data['hostname'], session)                        
                        if tracker_id:
                            session.query(TrackedRoom).filter_by(room_id=room_id).update({'tracker_id': tracker_id})
                            session.commit()
                            new_data['tracker_id'] = tracker_id
                        else:
                            print(f"[SUPERVISOR] Failed to set up {room_id}. Will retry later.")
                            continue

                    print(f"[SUPERVISOR] Starting poller for room: '{new_data['alias']}'")
                    task = asyncio.create_task(poll_room_with_interval(new_data))
                    running_tasks[room_id] = {'task': task, 'data': new_data}

            # --- Check for deleted rooms ---
            deleted_room_ids = set(running_tasks.keys()) - set(current_rooms_data.keys())
            for room_id in deleted_room_ids:
                task_info = running_tasks.pop(room_id)
                print(f"[SUPERVISOR] Room '{task_info['data']['alias']}' is no longer tracked. Stopping poller.")
                task_info['task'].cancel()

        except Exception as e:
            print(f"[SUPERVISOR] An error occurred: {e}")
        finally:
            Session.remove()

        await asyncio.sleep(SUPERVISOR_INTERVAL_SECONDS)


async def poll_room_with_interval(room_info):
    while True:
        try: await poll_room_instance(room_info)
        except asyncio.CancelledError: break
        except Exception as e: print(f"[POLLER][{room_info['alias']}] Unhandled error: {e}")
        await asyncio.sleep(POLLING_INTERVAL_SECONDS)

def run_poller(): asyncio.run(poller_supervisor())

# ==============================================================================
# 5. MAIN EXECUTION
# ==============================================================================

if __name__ == "__main__":
    print("[MAIN] AP Tracker Service starting...")
    Base.metadata.create_all(engine)
    print("[MAIN] Database tables verified/created.")
    api_thread = Thread(target=lambda: serve(app, host='0.0.0.0', port=5000), daemon=True)
    api_thread.start()
    print("[MAIN] API server started on http://0.0.0.0:5000")
    try:
        run_poller()
    except KeyboardInterrupt:
        print("\n[MAIN] Service stopped by user. Shutting down.")