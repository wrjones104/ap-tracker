from dotenv import load_dotenv
import os
import sys
import requests
import json
import time
import asyncio
import websockets
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Boolean, DateTime, or_
from sqlalchemy.orm import relationship, sessionmaker, declarative_base
from flask import Flask, request, jsonify
from threading import Thread
import firebase_admin
from firebase_admin import credentials, messaging
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

# --- NEW: Lazy Initialization Setup ---
# We declare the engine and Session variables here, but we don't create them yet.
datapackage_cache = {}
engine = None
Session = None
Base = declarative_base()

def init_db():
    """
    This function will be called to create the database engine and session.
    It will only run once per process.
    """
    global engine, Session

    # Check if the engine has already been initialized in this process
    if engine is not None:
        return

    print("--- INITIALIZING DATABASE AND FIREBASE CONNECTION ---", file=sys.stderr)

    DB_PATH = os.environ.get('AP_DB_PATH', 'ap_tracker.db')
    CRED_PATH = os.environ.get('AP_CRED_PATH', 'service-account-key.json')

    # Now, create the engine and session
    DATABASE_FILE = DB_PATH
    print(f"--- DB_PATH from env: {DB_PATH}")
    print(f"--- DATABASE_FILE: {DATABASE_FILE}")
    print(f"--- Absolute path: {os.path.abspath(DATABASE_FILE)}")

    engine = create_engine(f"sqlite:///{os.path.abspath(DATABASE_FILE)}", connect_args={"check_same_thread": False})
    print(f"--- Engine URL: {engine.url}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    # Initialize Firebase
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(CRED_PATH)
            firebase_admin.initialize_app(cred)
            print("Firebase initialized successfully.", file=sys.stderr)
    except Exception as e:
        print(f"!!! FIREBASE ERROR: Could not initialize Firebase. Push notifications will NOT work. Error: {e}", file=sys.stderr)


# --- Database Models (Unchanged) ---
class TrackedRoom(Base):
    __tablename__ = 'tracked_rooms'
    id = Column(Integer, primary_key=True)
    room_id = Column(String, nullable=False, unique=True)
    alias = Column(String)
    tracker_id = Column(String)
    slots = relationship("TrackedSlot", back_populates="room", cascade="all, delete-orphan")
    hints = relationship("RevealedHint", back_populates="room", cascade="all, delete-orphan")
    notified_items = relationship("NotifiedItem", back_populates="room", cascade="all, delete-orphan")

class TrackedSlot(Base):
    __tablename__ = 'tracked_slots'
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey('tracked_rooms.id'), nullable=False)
    slot_id = Column(Integer, nullable=False)
    slot_name = Column(String, nullable=False)
    game_name = Column(String)
    room = relationship("TrackedRoom", back_populates="slots")

class RevealedHint(Base):
    __tablename__ = 'revealed_hints'
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey('tracked_rooms.id'), nullable=False)
    item_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    item_owner_id = Column(Integer, nullable=False)
    location_owner_id = Column(Integer, nullable=False)
    found = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    room = relationship("TrackedRoom", back_populates="hints")

class NotifiedItem(Base):
    __tablename__ = 'notified_items'
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey('tracked_rooms.id'), nullable=False)
    receiving_slot_id = Column(Integer, nullable=False)
    item_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    room = relationship("TrackedRoom", back_populates="notified_items")

class DeviceToken(Base):
    __tablename__ = 'device_tokens'
    id = Column(Integer, primary_key=True)
    token = Column(String, nullable=False, unique=True)


# --- Flask App Setup ---
app = Flask(__name__)
ARCHIPELAGO_HOST = "archipelago.gg"

@app.before_request
def before_request():
    init_db()


# --- API Endpoints ---
@app.route('/import/cheesetracker', methods=['POST'])
def import_from_cheesetracker():
    data = request.json
    if not data or 'api_key' not in data:
        return jsonify({'error': 'Missing api_key'}), 400

    api_key = data['api_key']
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Accept': 'application/json'
    }
    cheesetracker_url = "https://cheesetrackers.theincrediblewheelofchee.se/api/v3/user/tracked"

    try:
        response = requests.get(cheesetracker_url, headers=headers, timeout=10)
        response.raise_for_status()
        try:
            ct_data = response.json()
        except json.JSONDecodeError:
            print(f"Cheesetracker API ERROR: Status Code: {response.status_code}, Raw text: {response.text}")
            return jsonify({'error': 'Cheesetracker API returned a non-JSON response.'}), 502
    except requests.RequestException as e:
        return jsonify({'error': f'Could not connect to Cheesetracker API: {e}'}), 502

    rooms_found = []
    for room_data in ct_data.get('rooms', []):
        room_info = room_data.get('room', {})
        players_to_track = [{'slot_id': s.get('slot'), 'name': s.get('name')} for s in room_data.get('tracked_slots', [])]
        rooms_found.append({
            'room_id': room_info.get('id'),
            'alias': room_info.get('name', 'Cheesetracker Import'),
            'players_to_track': players_to_track
        })
    return jsonify({'rooms_found': rooms_found})


@app.route('/rooms', methods=['GET'])
def get_rooms():
    session = Session()
    try:
        rooms = session.query(TrackedRoom).all()
        rooms_with_details = []
        for room in rooms:
            tracked_count = len(room.slots)
            total_slots, host_and_port = 0, "archipelago.gg"
            try:
                url = f"https://{ARCHIPELAGO_HOST}/api/room_status/{room.room_id}"
                response = requests.get(url, timeout=5)
                if response.ok:
                    data = response.json()
                    total_slots = len(data.get('players', []))
                    if port := data.get('last_port'):
                        host_and_port = f"archipelago.gg:{port}"
            except requests.RequestException: pass
            rooms_with_details.append({
                'id': room.id, 'room_id': room.room_id, 'alias': room.alias,
                'host': host_and_port, 'tracked_slots_count': tracked_count,
                'total_slots_count': total_slots
            })
        return jsonify(rooms_with_details)
    finally:
        session.close()

@app.route('/room', methods=['POST'])
def add_room():
    data = request.json
    if not data or 'room_id' not in data or 'alias' not in data:
        return jsonify({'error': 'Missing room_id or alias'}), 400

    session = Session()
    try:
        if session.query(TrackedRoom).filter_by(room_id=data['room_id']).first():
            return jsonify({'error': 'Room already exists'}), 409
        new_room = TrackedRoom(room_id=data['room_id'], alias=data['alias'])
        session.add(new_room)
        session.commit()
        return jsonify({'success': f"Room '{data['alias']}' added."}), 201
    finally:
        session.close()

@app.route('/room/<int:room_db_id>', methods=['DELETE'])
def delete_room(room_db_id):
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
        if room:
            session.delete(room)
            session.commit()
            return jsonify({'success': f"Room '{room.alias}' deleted."})
        return jsonify({'error': 'Room not found'}), 404
    finally:
        session.close()

@app.route('/room/<int:room_db_id>', methods=['PUT'])
def update_room(room_db_id):
    data = request.json
    if not data or 'alias' not in data:
        return jsonify({'error': 'Missing alias in request body'}), 400

    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
        if room:
            room.alias = data['alias']
            session.commit()
            return jsonify({'success': 'Room alias updated.'})
        return jsonify({'error': 'Room not found'}), 404
    finally:
        session.close()


@app.route('/room/<int:room_db_id>/players', methods=['GET'])
def get_room_players(room_db_id):
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
        if not room: return jsonify({'error': 'Room not found'}), 404
        tracked_slot_ids = {slot.slot_id for slot in room.slots}
    finally:
        session.close()

    try:
        url = f"https://{ARCHIPELAGO_HOST}/api/room_status/{room.room_id}"
        response = requests.get(url, timeout=30); response.raise_for_status()
        live_players = response.json().get('players', [])
    except requests.RequestException as e:
        return jsonify({'error': f'Could not fetch player list from Archipelago: {e}'}), 500

    player_list_for_app = [{'slot_id': i + 1, 'name': p[0], 'game': p[1], 'is_tracked': (i + 1) in tracked_slot_ids} for i, p in enumerate(live_players)]
    return jsonify(player_list_for_app)


@app.route('/room/<int:room_db_id>/history/items', methods=['GET'])
def get_item_history(room_db_id):
    session = Session()
    try:
        tracked_slots_query = session.query(TrackedSlot.slot_id).filter_by(room_id=room_db_id).all()
        if not tracked_slots_query:
            return jsonify([])
        tracked_slot_ids = {slot_id for (slot_id,) in tracked_slots_query}

        items = session.query(NotifiedItem).filter(
            NotifiedItem.room_id == room_db_id,
            NotifiedItem.receiving_slot_id.in_(tracked_slot_ids)
        ).order_by(NotifiedItem.id.desc()).all()

        room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
        if not room: return jsonify([])

        player_list_response = get_room_players(room_db_id)
        if player_list_response.status_code != 200:
            name_map, game_map = {}, {}
        else:
            player_list = player_list_response.get_json()
            name_map = {p['slot_id']: p['name'] for p in player_list}
            game_map = {p['slot_id']: p['game'] for p in player_list}

        history = []
        for item in items:
            receiver_name = name_map.get(item.receiving_slot_id, f"Player {item.receiving_slot_id}")
            item_name = get_name_from_datapackage(item.item_id, item.receiving_slot_id, game_map, 'item_id_to_name')
            history.append({
                "message": f"{receiver_name} received: {item_name}",
                "timestamp": item.timestamp.isoformat() + "Z"
            })
        return jsonify(history)
    finally:
        session.close()

@app.route('/room/<int:room_db_id>/history/hint', methods=['GET'])
def get_hint_history(room_db_id):
    session = Session()
    try:
        tracked_slots_query = session.query(TrackedSlot.slot_id).filter_by(room_id=room_db_id).all()
        if not tracked_slots_query:
            return jsonify([])
        tracked_slot_ids = {slot_id for (slot_id,) in tracked_slots_query}

        hints = session.query(RevealedHint).filter(
            RevealedHint.room_id == room_db_id,
            or_(
                RevealedHint.item_owner_id.in_(tracked_slot_ids),
                RevealedHint.location_owner_id.in_(tracked_slot_ids)
            )
        ).order_by(RevealedHint.id.desc()).all()

        room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
        if not room: return jsonify([])

        player_list_response = get_room_players(room_db_id)
        if player_list_response.status_code != 200:
            name_map, game_map = {}, {}
        else:
            player_list = player_list_response.get_json()
            name_map = {p['slot_id']: p['name'] for p in player_list}
            game_map = {p['slot_id']: p['game'] for p in player_list}

        history = []
        for hint in hints:
            item_owner_name = name_map.get(hint.item_owner_id, f"Player {hint.item_owner_id}")
            location_owner_name = name_map.get(hint.location_owner_id, f"Player {hint.location_owner_id}")
            item_name = get_name_from_datapackage(hint.item_id, hint.item_owner_id, game_map, 'item_id_to_name')
            location_name = get_name_from_datapackage(hint.location_id, hint.location_owner_id, game_map, 'location_id_to_name')

            history.append({
                "message": f"Hint for {item_owner_name}: '{item_name}' is at '{location_name}' in {location_owner_name}'s world.",
                "timestamp": hint.timestamp.isoformat() + "Z"
            })
        return jsonify(history)
    finally:
        session.close()

@app.route('/room/<int:room_db_id>/slots', methods=['PUT'])
def update_tracked_slots(room_db_id):
    data = request.json
    if 'tracked_slot_ids' not in data or not isinstance(data['tracked_slot_ids'], list):
        return jsonify({'error': 'Request must include a list of tracked_slot_ids'}), 400

    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
        if not room: return jsonify({'error': 'Room not found'}), 404

        session.query(TrackedSlot).filter_by(room_id=room.id).delete()
        try:
            url = f"https://{ARCHIPELAGO_HOST}/api/room_status/{room.room_id}"
            response = requests.get(url, timeout=10); response.raise_for_status()
            players_list = response.json().get('players', [])
        except requests.RequestException as e:
            return jsonify({'error': f'Could not fetch player list: {e}'}), 500

        for slot_id in data['tracked_slot_ids']:
            try:
                player_data = players_list[int(slot_id) - 1]
                session.add(TrackedSlot(room_id=room.id, slot_id=slot_id, slot_name=player_data[0], game_name=player_data[1]))
            except (IndexError, ValueError):
                print(f"Warning: Invalid slot_id {slot_id} provided for room {room.alias}.")
        session.commit()
        return jsonify({'success': 'Tracked slots updated.'})
    finally:
        session.close()

@app.route('/register', methods=['POST'])
def register_device():
    data = request.json
    if not data or 'token' not in data: return jsonify({'error': 'Missing device token'}), 400
    session = Session()
    try:
        if not session.query(DeviceToken).filter_by(token=data['token']).first():
            session.add(DeviceToken(token=data['token']))
            session.commit()
        return jsonify({'success': 'Device registered.'}), 201
    finally:
        session.close()

@app.route('/unregister', methods=['POST'])
def unregister_device():
    data = request.json
    if not data or 'token' not in data: return jsonify({'error': 'Missing device token'}), 400
    session = Session()
    try:
        token_to_delete = session.query(DeviceToken).filter_by(token=data['token']).first()
        if token_to_delete:
            session.delete(token_to_delete)
            session.commit()
        return jsonify({'success': 'Device unregistered.'})
    finally:
        session.close()


# --- Polling Service Logic ---
def send_push_notification(title, body, room_alias):
    session = Session()
    try:
        tokens = [t.token for t in session.query(DeviceToken).all()]
        if not tokens:
            print("Push notification not sent: No registered devices.")
            return
        full_title = f"[{room_alias}] {title}"
        messages = [messaging.Message(notification=messaging.Notification(title=full_title, body=body), token=token) for token in tokens]
        response = messaging.send_each(messages)
        if response.failure_count > 0:
            print(f"Failed to send {response.failure_count} push notifications.")
    except Exception as e:
        print(f"Error sending push notification: {e}")
    finally:
        session.close()

def get_name_from_datapackage(entity_id, player_id, game_map, map_key):
    game = game_map.get(player_id)
    if player_id == 0: game = "Archipelago"
    if game and game in datapackage_cache:
        entity_map = datapackage_cache[game].get(map_key, {})
        return entity_map.get(str(entity_id), f"ID {entity_id}")
    return f"ID {entity_id}"

async def initial_room_setup(room: TrackedRoom, session: Session):
    print(f"[{room.alias}] Performing initial setup...")
    try:
        url = f"https://{ARCHIPELAGO_HOST}/api/room_status/{room.room_id}"
        response = requests.get(url, timeout=10); response.raise_for_status()
        room_info = response.json()
        port, tracker_id = room_info.get('last_port'), room_info.get('tracker')
        if not all((port, tracker_id)):
            print(f"[{room.alias}] Error: Could not find port or tracker ID.")
            return None, None

        is_first_time_setup = room.tracker_id != tracker_id
        room.tracker_id = tracker_id
        session.merge(room); session.commit()

        player_name_map = {i + 1: p[0] for i, p in enumerate(room_info.get('players', []))}
        player_game_map = {i + 1: p[1] for i, p in enumerate(room_info.get('players', []))}

        uri = f"wss://{ARCHIPELAGO_HOST}:{port}"
        async with websockets.connect(
            uri,
            open_timeout=10,
            ping_interval=20
        ) as websocket:
            message = await asyncio.wait_for(websocket.recv(), timeout=10)
            checksums = json.loads(message)[0].get('datapackage_checksums', {})
        for game, checksum in checksums.items():
            if game not in datapackage_cache:
                url = f"https://{ARCHIPELAGO_HOST}/api/datapackage/{checksum}"
                response = requests.get(url, timeout=10); response.raise_for_status()
                game_data = response.json()
                if 'item_name_to_id' in game_data: game_data['item_id_to_name'] = {str(v): k for k, v in game_data['item_name_to_id'].items()}
                if 'location_name_to_id' in game_data: game_data['location_id_to_name'] = {str(v): k for k, v in game_data['location_name_to_id'].items()}
                datapackage_cache[game] = game_data

        if is_first_time_setup:
            print(f"[{room.alias}] First-time setup. Establishing notification baseline...")
            tracker_url = f"https://{ARCHIPELAGO_HOST}/api/tracker/{tracker_id}"
            tracker_response = requests.get(tracker_url, timeout=10); tracker_response.raise_for_status()
            tracker_data = tracker_response.json()
            process_tracker_data(room, tracker_data, set(player_name_map.keys()), player_name_map, player_game_map, suppress_notifications=True)
            print(f"[{room.alias}] Baseline established.")

        print(f"[{room.alias}] Setup complete.")
        return player_name_map, player_game_map
    except Exception as e:
        print(f"[{room.alias}] An error occurred during setup: {e}")
        return None, None

def process_tracker_data(room: TrackedRoom, data: dict, tracked_slot_ids: set, name_map: dict, game_map: dict, suppress_notifications=False):
    session = Session()
    try:
        finished_player_ids = set()
        player_statuses_raw = data.get('player_status')
        if isinstance(player_statuses_raw, dict):
            for slot_id_str, status_code in player_statuses_raw.items():
                slot_id = int(slot_id_str)
                if slot_id in tracked_slot_ids and status_code == 30: finished_player_ids.add(slot_id)
        elif isinstance(player_statuses_raw, list):
            for status_info in player_statuses_raw:
                slot_id, status_code = -1, -1
                if isinstance(status_info, dict) and 'player' in status_info and 'status' in status_info:
                    slot_id, status_code = status_info['player'], status_info['status']
                elif isinstance(status_info, (list, tuple)) and len(status_info) >= 2:
                    slot_id, status_code, *_ = status_info
                if slot_id != -1 and int(slot_id) in tracked_slot_ids and status_code == 30:
                    finished_player_ids.add(int(slot_id))

        for slot_id in finished_player_ids:
            if not suppress_notifications: send_push_notification(f"Player Finished!", f"{name_map.get(slot_id)} has finished the game.", room.alias)
            slot_to_remove = session.query(TrackedSlot).filter_by(room_id=room.id, slot_id=slot_id).first()
            if slot_to_remove: session.delete(slot_to_remove)
        active_tracked_slots = tracked_slot_ids - finished_player_ids
        for player_items in data.get('player_items_received', []):
            receiver_id = player_items.get('player')
            if receiver_id in active_tracked_slots:
                for item_id, location_id, _, flags in player_items.get('items', []):
                    item_name = get_name_from_datapackage(item_id, receiver_id, game_map, 'item_id_to_name')
                    hint = session.query(RevealedHint).filter_by(room_id=room.id, item_id=item_id, location_id=location_id).first()
                    if hint and not hint.found:
                        if not suppress_notifications: send_push_notification(f"Hinted Item Found!", f"{name_map.get(receiver_id)} found: {item_name}", room.alias)
                        hint.found = True
                        continue
                    if bool(flags & 1) and not session.query(NotifiedItem).filter_by(room_id=room.id, receiving_slot_id=receiver_id, item_id=item_id, location_id=location_id).first():
                        if not suppress_notifications: send_push_notification(f"Progression Item!", f"{name_map.get(receiver_id)} received: {item_name}", room.alias)
                        session.add(NotifiedItem(room_id=room.id, receiving_slot_id=receiver_id, item_id=item_id, location_id=location_id))
        for player_hints in data.get('hints', []):
            for hint_data in player_hints.get('hints', []):
                item_owner_id, location_owner_id, location_id, item_id, *_ = hint_data
                is_item_owner_tracked, is_loc_owner_tracked = item_owner_id in active_tracked_slots, location_owner_id in active_tracked_slots
                if (is_item_owner_tracked or is_loc_owner_tracked) and not session.query(RevealedHint).filter_by(room_id=room.id, item_id=item_id, location_id=location_id, item_owner_id=item_owner_id, location_owner_id=location_owner_id).first():
                    if not suppress_notifications:
                        item_name, loc_name = get_name_from_datapackage(item_id, item_owner_id, game_map, 'item_id_to_name'), get_name_from_datapackage(location_id, location_owner_id, game_map, 'location_id_to_name')
                        item_owner_name, loc_owner_name = name_map.get(item_owner_id), name_map.get(location_owner_id)
                        if is_item_owner_tracked:
                            send_push_notification(f"New Hint for {item_owner_name}!", f"Your '{item_name}' is in {loc_owner_name}'s world at '{loc_name}'.", room.alias)
                        elif is_loc_owner_tracked:
                            send_push_notification(f"Item Hinted in {loc_owner_name}'s World!", f"'{item_name}' for {item_owner_name} is at your location: '{loc_name}'.", room.alias)
                    session.add(RevealedHint(room_id=room.id, item_id=item_id, location_id=location_id, item_owner_id=item_owner_id, location_owner_id=location_owner_id))
        session.commit()
    finally:
        session.close()

async def poll_room(room: TrackedRoom):
    while True:
        session = Session()
        try:
            name_map, game_map = await initial_room_setup(room, session)
            if all((name_map, game_map)):
                print(f"[{room.alias}] Setup successful, starting main polling loop.")
                break
            else:
                print(f"[{room.alias}] Setup failed. Will retry in {POLLING_INTERVAL_SECONDS * 3} seconds.")
                await asyncio.sleep(POLLING_INTERVAL_SECONDS * 3)
        finally:
            session.close()

    while True:
        try:
            session = Session()
            tracked_slot_ids = {slot.slot_id for slot in session.query(TrackedSlot).filter_by(room_id=room.id).all()}
            session.close()
            if not tracked_slot_ids:
                print(f"[{time.strftime('%H:%M:%S')}][{room.alias}] No slots are tracked. Idling...")
            else:
                url = f"https://{ARCHIPELAGO_HOST}/api/tracker/{room.tracker_id}"
                response = requests.get(url, timeout=10); response.raise_for_status()
                data = response.json()
                print(f"[{time.strftime('%H:%M:%S')}][{room.alias}] Polled. Checking for updates for players {tracked_slot_ids}...")
                process_tracker_data(room, data, tracked_slot_ids, name_map, game_map)
        except asyncio.CancelledError:
            print(f"[{room.alias}] Polling cancelled. Shutting down task."); break
        except Exception as e:
            print(f"[{room.alias}] An error occurred during polling: {e}")
        await asyncio.sleep(POLLING_INTERVAL_SECONDS)

async def main():
    print("AP Tracking Service starting...")
    init_db() # Initialize the database for the poller process
    
    running_tasks = {}
    while True:
        session = Session()
        try:
            rooms_in_db = session.query(TrackedRoom).all()
            db_room_ids = {room.id for room in rooms_in_db}
            for room in rooms_in_db:
                if room.id not in running_tasks:
                    print(f"[SERVICE] New room detected: '{room.alias}'. Starting poller.")
                    task = asyncio.create_task(poll_room(room))
                    running_tasks[room.id] = task
            deleted_room_ids = set(running_tasks.keys()) - db_room_ids
            for room_id in deleted_room_ids:
                print(f"[SERVICE] Room with ID {room_id} removed from DB. Stopping poller.")
                task = running_tasks.pop(room_id)
                task.cancel()
        finally:
            session.close()
        await asyncio.sleep(30)


# --- Main Execution Block ---
if __name__ == "__main__":
    if '--run-poller' in sys.argv:
        POLLING_INTERVAL_SECONDS = 60
        print("Starting AP Tracker Polling Service...")
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("\nPolling service stopped by user.")
    else:
        from waitress import serve
        init_db() # Initialize for local dev server
        print("Starting API server for local development on http://0.0.0.0:5000")
        serve(app, host='0.0.0.0', port=5000)
