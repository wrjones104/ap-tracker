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
from datetime import datetime, timezone
from functools import wraps

# --- Core Dependencies ---
from flask import Flask, request, jsonify
from waitress import serve
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime, UniqueConstraint, event
from sqlalchemy.orm import relationship, sessionmaker, declarative_base, scoped_session
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Firebase for Push Notifications ---
import firebase_admin
from firebase_admin import credentials, messaging

# ==============================================================================
# 1. CONFIGURATION & INITIALIZATION
# ==============================================================================

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
    tracker_id = Column(String)
    game_checksums_json = Column(String, default='{}') # Stores a JSON map of game->checksum for this room
    slots = relationship("TrackedSlot", back_populates="room", cascade="all, delete-orphan")

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
    rooms_data = []
    for room in session.query(TrackedRoom).all():
        total_slots, host = 0, "archipelago.gg"
        try:
            url = f"https://{ARCHIPELAGO_HOST}/api/room_status/{room.room_id}"
            response = requests.get(url, timeout=5)
            if response.ok:
                data = response.json()
                total_slots = len(data.get('players', []))
                if port := data.get('last_port'): host = f"archipelago.gg:{port}"
        except requests.RequestException: pass
        rooms_data.append({'id': room.id, 'room_id': room.room_id, 'alias': room.alias, 'tracked_slots_count': len(room.slots), 'host': host, 'total_slots_count': total_slots})
    return jsonify(rooms_data)

@app.route('/rooms', methods=['POST'])
@handle_db_errors
def add_tracked_room():
    data = request.json
    if not data or 'room_id' not in data or 'alias' not in data: return jsonify({'error': 'Missing room_id or alias'}), 400
    room_id = data['room_id']
    try:
        url = f"https://{ARCHIPELAGO_HOST}/api/room_status/{room_id}"
        response = requests.get(url, timeout=10)
        if response.status_code >= 400: return jsonify({'error': f'Invalid room (status {response.status_code}).'}), 400
    except requests.RequestException as e: return jsonify({'error': f'Could not validate room: {e}'}), 502
    session = Session()
    if session.query(TrackedRoom).filter_by(room_id=room_id).first(): return jsonify({'error': 'Room already tracked'}), 409
    new_room = TrackedRoom(room_id=room_id, alias=data['alias'])
    session.add(new_room)
    session.commit()
    return jsonify({'message': f"Room '{new_room.alias}' added.", 'id': new_room.id}), 201

@app.route('/rooms/<int:room_db_id>', methods=['PUT'])
@handle_db_errors
def update_tracked_room(room_db_id):
    data = request.json
    if not data or 'alias' not in data: return jsonify({'error': 'Missing alias'}), 400
    session = Session()
    room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
    if not room: return jsonify({'error': 'Room not found'}), 404
    room.alias = data['alias']
    session.commit()
    return jsonify({'message': 'Alias updated.'})

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
    if not room: return jsonify({'error': 'Room not found'}), 404
    tracked_slot_ids = {slot.slot_id for slot in room.slots}
    try:
        url = f"https://{ARCHIPELAGO_HOST}/api/room_status/{room.room_id}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        players = response.json().get('players', [])
    except requests.RequestException as e: return jsonify({'error': f'Could not fetch players: {e}'}), 502
    player_list = [{'slot_id': i + 1, 'name': p[0], 'game': p[1], 'is_tracked': (i + 1) in tracked_slot_ids} for i, p in enumerate(players)]
    return jsonify(player_list)

@app.route('/rooms/<int:room_db_id>/slots', methods=['PUT'])
@handle_db_errors
def update_tracked_slots(room_db_id):
    data = request.json
    if 'tracked_slot_ids' not in data: return jsonify({'error': 'Missing tracked_slot_ids'}), 400
    session = Session()
    room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
    if not room: return jsonify({'error': 'Room not found'}), 404
    session.query(TrackedSlot).filter_by(room_id=room.id).delete()
    for slot_id in data['tracked_slot_ids']:
        if isinstance(slot_id, int) and slot_id > 0: session.add(TrackedSlot(room_id=room.id, slot_id=slot_id))
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
    items = session.query(NotifiedItem).filter(NotifiedItem.room_id == room.room_id, NotifiedItem.receiving_slot_id.in_(tracked_slot_ids)).order_by(NotifiedItem.id.desc()).limit(100).all()
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
        history.append({"message": f"{receiver_name} received: {item_name}", "timestamp": item.timestamp.replace(tzinfo=timezone.utc).isoformat()})
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
            messages.append(messaging.Message(
                notification=messaging.Notification(title=content['title'], body=content['body']),
                token=token
            ))
    
    if not messages:
        return

    loop = asyncio.get_running_loop()
    for i in range(0, len(messages), 10):
        chunk = messages[i:i + 10]
        try:
            response = await loop.run_in_executor(None, lambda: messaging.send_each(chunk))
            if response.failure_count > 0:
                failed = [chunk[i].token for i, r in enumerate(response.responses) if not r.success and hasattr(r.exception, 'code') and r.exception.code == 'UNREGISTERED']
                if failed:
                    session = Session()
                    session.query(Device).filter(Device.fcm_token.in_(failed)).delete(synchronize_session=False)
                    session.commit()
            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[FCM] Error sending chunk: {e}")

async def fetch_json(url):
    session = get_aiohttp_session()
    try:
        async with session.get(url, timeout=15) as response:
            response.raise_for_status()
            return await response.json()
    except Exception as e: return None

async def poll_room_instance(room_info):
    room_id, tracker_id, room_alias = room_info['room_id'], room_info['tracker_id'], room_info['alias']
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}][{room_alias}] Polling tracker...")
    session = Session()
    db_room = session.query(TrackedRoom).filter(TrackedRoom.room_id == room_id).first()
    if not db_room: return
    game_checksums = json.loads(db_room.game_checksums_json)
    all_tracked_slots = {slot.slot_id for slot in db_room.slots}
    if not all_tracked_slots: return
    tracker_data = await fetch_json(f"https://{ARCHIPELAGO_HOST}/api/tracker/{tracker_id}")
    if not tracker_data: return
    room_status_data = await fetch_json(f"https://{ARCHIPELAGO_HOST}/api/room_status/{room_id}")
    players = room_status_data.get('players', []) if room_status_data else []
    name_map = {i + 1: p[0] for i, p in enumerate(players)}
    game_map = {i + 1: p[1] for i, p in enumerate(players)}
    device_tokens = [d.fcm_token for d in session.query(Device.fcm_token).all()]
    if not device_tokens: return
    
    unique_notification_contents = set()
    
    finished_player_ids = set()
    player_statuses_raw = tracker_data.get('player_status', {})
    if isinstance(player_statuses_raw, dict):
        for slot_id_str, status_code in player_statuses_raw.items():
            slot_id = int(slot_id_str)
            if slot_id in all_tracked_slots and status_code == 30:
                finished_player_ids.add(slot_id)
    elif isinstance(player_statuses_raw, list):
        for status_info in player_statuses_raw:
            slot_id, status_code = -1, -1
            if isinstance(status_info, dict) and 'player' in status_info and 'status' in status_info:
                slot_id, status_code = status_info['player'], status_info['status']
            elif isinstance(status_info, (list, tuple)) and len(status_info) >= 2:
                slot_id, status_code, *_ = status_info
            
            if slot_id != -1 and int(slot_id) in all_tracked_slots and status_code == 30:
                finished_player_ids.add(int(slot_id))

    if finished_player_ids:
        for slot_id in finished_player_ids:
            name = name_map.get(slot_id, f"P{slot_id}")
            unique_notification_contents.add((f"[{room_alias}] 🏁 Player Finished!", f"{name} has finished."))
            if slot := session.query(TrackedSlot).filter_by(room_id=db_room.id, slot_id=slot_id).first(): session.delete(slot)
        session.commit()
    
    active_tracked_slots = all_tracked_slots - finished_player_ids
    if not active_tracked_slots:
        if unique_notification_contents:
            notifications_to_send = [{'title': t, 'body': b} for t, b in unique_notification_contents]
            print(f"[{timestamp}][{room_alias}] Found {len(notifications_to_send)} unique events. Sending notifications to {len(device_tokens)} devices.")
            for n in notifications_to_send: print(f"  - {n['title']} {n['body']}")
            await send_push_notifications(notifications_to_send, device_tokens)
        return

    existing_items = {(i.receiving_slot_id, i.item_id, i.location_id) for i in session.query(NotifiedItem).filter_by(room_id=room_id)}
    existing_hints = {(h.item_owner_id, h.location_owner_id, h.item_id, h.location_id) for h in session.query(NotifiedHint).filter_by(room_id=room_id)}
    newly_notified_items, newly_notified_hints = [], []
    for p_items in tracker_data.get('player_items_received', []):
        rid = p_items.get('player')
        if rid in active_tracked_slots:
            for item_id, loc_id, _, flags in p_items.get('items', []):
                if bool(flags & 1) and (rid, item_id, loc_id) not in existing_items:
                    r_game = game_map.get(rid, "Unknown")
                    r_checksum = game_checksums.get(r_game)
                    i_name = session.query(DatapackageCache.entity_name).filter_by(game=r_game, checksum=r_checksum, entity_type='item', entity_id=item_id).scalar() or f"ID {item_id}"
                    unique_notification_contents.add((f"[{room_alias}] ✨ Progression Item!", f"{name_map.get(rid, f'P{rid}')} received: {i_name}"))
                    newly_notified_items.append(NotifiedItem(room_id=room_id, receiving_slot_id=rid, item_id=item_id, location_id=loc_id))
                    existing_items.add((rid, item_id, loc_id))
    for p_hints in tracker_data.get('hints', []):
        for hint_data in p_hints.get('hints', []):
            io_id, lo_id, loc_id, item_id, *_ = hint_data
            if (io_id in active_tracked_slots or lo_id in active_tracked_slots) and (io_id, lo_id, item_id, loc_id) not in existing_hints:
                io_game, lo_game = game_map.get(io_id, "Unknown"), game_map.get(lo_id, "Unknown")
                io_checksum, lo_checksum = game_checksums.get(io_game), game_checksums.get(lo_game)
                i_name = session.query(DatapackageCache.entity_name).filter_by(game=io_game, checksum=io_checksum, entity_type='item', entity_id=item_id).scalar() or f"ID {item_id}"
                l_name = session.query(DatapackageCache.entity_name).filter_by(game=lo_game, checksum=lo_checksum, entity_type='location', entity_id=loc_id).scalar() or f"ID {loc_id}"
                
                if io_id in active_tracked_slots:
                    unique_notification_contents.add((f"[{room_alias}] 🔔 New Hint for {name_map.get(io_id)}!", f"Your '{i_name}' is in {name_map.get(lo_id)}'s world at '{l_name}'."))
                
                if lo_id in active_tracked_slots and io_id != lo_id:
                    unique_notification_contents.add((f"[{room_alias}] 🔎 Item Hinted in your World!", f"'{i_name}' for {name_map.get(io_id)} is at your location: '{l_name}'."))

                newly_notified_hints.append(NotifiedHint(room_id=room_id, item_owner_id=io_id, location_owner_id=lo_id, item_id=item_id, location_id=loc_id))
                existing_hints.add((io_id, lo_id, item_id, loc_id))
                
    if newly_notified_items: session.bulk_save_objects(newly_notified_items)
    if newly_notified_hints: session.bulk_save_objects(newly_notified_hints)
    if newly_notified_items or newly_notified_hints: session.commit()

    if unique_notification_contents:
        notifications_to_send = [{'title': t, 'body': b} for t, b in unique_notification_contents]
        print(f"[{timestamp}][{room_alias}] Found {len(notifications_to_send)} unique events. Sending notifications to {len(device_tokens)} devices.")
        for n in notifications_to_send: print(f"  - {n['title']} {n['body']}")
        await send_push_notifications(notifications_to_send, device_tokens)
    elif not finished_player_ids: 
        print(f"[{timestamp}][{room_alias}] No new events found.")

async def setup_and_cache_datapackage(room_id, session):
    try:
        room_info = await fetch_json(f"https://{ARCHIPELAGO_HOST}/api/room_status/{room_id}")
        if not room_info: return None
        tracker_id, port = room_info.get('tracker'), room_info.get('last_port')
        if not tracker_id or not port: return None
        uri = f"wss://{ARCHIPELAGO_HOST}:{port}"
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
            game_data = await fetch_json(f"https://{ARCHIPELAGO_HOST}/api/datapackage/{checksum}")
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
    running_tasks = {} # Will now store {'task': task_obj, 'data': room_dict}

    while True:
        session = Session()
        try:
            rooms_in_db = session.query(TrackedRoom).all()
            current_rooms_data = {r.room_id: {'tracker_id': r.tracker_id, 'alias': r.alias, 'room_id': r.room_id} for r in rooms_in_db}
            
            # --- Check for new or changed rooms ---
            for room_id, new_data in current_rooms_data.items():
                task_info = running_tasks.get(room_id)

                # If task doesn't exist or data has changed, (re)start it
                if not task_info or task_info['data'] != new_data:
                    if task_info: # It's a change, not a new room
                        print(f"[SUPERVISOR] Data for room '{task_info['data']['alias']}' has changed. Restarting poller.")
                        task_info['task'].cancel()
                    
                    # Ensure tracker_id is set before starting
                    if not new_data['tracker_id']:
                        print(f"[SUPERVISOR] First time seeing room {room_id}. Performing setup...")
                        tracker_id = await setup_and_cache_datapackage(room_id, session)
                        if tracker_id:
                            # We need to update the DB AND our in-memory data
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

