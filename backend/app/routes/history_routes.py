import logging
import json
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from sqlalchemy.orm import selectinload
from sqlalchemy import or_, desc, tuple_

from app import Session
from app.models import (
    TrackedRoom, UserRoomSubscription, UserTrackedSlot,
    DatapackageCache, NotifiedItem, NotifiedHint, SlotItemCount
)
from app.routes.common import log_api_call, token_required, handle_db_errors, format_iso_z

history_bp = Blueprint('history_routes', __name__)

def process_hints_for_user(session, user_id, room_db_id=None, since_timestamp=None, include_found=False):
    tracked_slots_query = session.query(UserTrackedSlot.room_id, UserTrackedSlot.slot_id).filter_by(user_id=user_id)
    if room_db_id:
        tracked_slots_query = tracked_slots_query.filter_by(room_id=room_db_id)

    user_tracked_tuples = {(ts.room_id, ts.slot_id) for ts in tracked_slots_query.all()}
    if not user_tracked_tuples:
        return {"hints_for_you": [], "hints_by_you": []}

    room_map_query = session.query(TrackedRoom.id, TrackedRoom.room_id)
    if room_db_id:
        room_map_query = room_map_query.filter_by(id=room_db_id)
    else:
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

    all_room_db_ids = list(room_id_to_uuid.keys())
    all_subs = session.query(UserRoomSubscription).filter(UserRoomSubscription.room_id.in_(all_room_db_ids)).all()
    alias_map = {sub.room_id: sub.alias for sub in all_subs}

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

    cache_keys_to_find = set()
    temp_hint_data = []

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

@history_bp.route('/rooms/<int:room_db_id>/history/items', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_item_history(current_user, room_db_id):
    session = Session()
    room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
    if not room:
        return jsonify({'error': 'Room not found'}), 404

    user_tracked_slots = session.query(UserTrackedSlot.slot_id, UserTrackedSlot.added_at).filter_by(
        user_id=current_user.id,
        room_id=room.id
    ).all()

    if not user_tracked_slots:
        return jsonify([]) 

    since_timestamp = request.args.get('since')
    since_dt = None
    if since_timestamp:
        try:
            since_dt = datetime.fromisoformat(since_timestamp.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            pass 

    tracked_slot_ids = {slot[0] for slot in user_tracked_slots}
    query = session.query(NotifiedItem).filter(
        NotifiedItem.room_id == room.room_id,
        NotifiedItem.receiving_slot_id.in_(tracked_slot_ids)
    )

    if since_dt:
        query = query.filter(NotifiedItem.timestamp > since_dt)

    query = query.order_by(NotifiedItem.id.asc() if since_dt else NotifiedItem.id.desc())

    try:
        limit = max(1, min(int(request.args.get('limit', 50)), 100))
        offset = max(int(request.args.get('offset', 0)), 0)
    except (ValueError, TypeError):
        limit = 50
        offset = 0
    
    query = query.limit(limit).offset(offset)
    items = query.all()

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

@history_bp.route('/history/sync', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def sync_history(current_user):
    data = request.json or {}
    session = Session()

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

    user_subs = session.query(UserRoomSubscription).options(
        selectinload(UserRoomSubscription.room)
    ).filter_by(
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

    tracked_set = set((slot.room_id, slot.slot_id) for slot in user_tracked_slots)
    
    item_watermarks_map = {}
    for item in data.get('items', []):
        r_id = item.get('room_db_id')
        s_id = item.get('slot_id')
        last_id = item.get('last_id')
        last_ts = item.get('last_timestamp')
        if (r_id, s_id) in tracked_set:
            item_watermarks_map[(r_id, s_id)] = {
                'last_id': last_id if isinstance(last_id, int) else None,
                'last_ts': last_ts
            }

    for (r_id, s_id) in tracked_set:
        if (r_id, s_id) not in item_watermarks_map:
            item_watermarks_map[(r_id, s_id)] = {'last_id': None, 'last_ts': None}

    # Pre-fetch max item IDs in DB for tracked rooms/slots to protect against out-of-bounds client cursors
    server_max_ids = {}
    if tracked_set:
        room_uuids_tracked = list(set(room_db_id_to_uuid.get(r_id) for (r_id, s_id) in tracked_set if room_db_id_to_uuid.get(r_id)))
        if room_uuids_tracked:
            from sqlalchemy import func
            max_id_query = session.query(
                NotifiedItem.room_id,
                NotifiedItem.receiving_slot_id,
                func.max(NotifiedItem.id).label('max_id')
            ).filter(
                NotifiedItem.room_id.in_(room_uuids_tracked)
            ).group_by(
                NotifiedItem.room_id,
                NotifiedItem.receiving_slot_id
            ).all()
            for ruuid, slot_id, max_id in max_id_query:
                server_max_ids[(ruuid, slot_id)] = max_id

    items = []
    if tracked_set:
        slot_filters = []
        for (r_id, s_id), w_info in item_watermarks_map.items():
            room_uuid = room_db_id_to_uuid.get(r_id)
            if not room_uuid:
                continue
            
            last_id = w_info.get('last_id')
            last_ts = w_info.get('last_ts')

            # Guard against stale client watermarks (client max_id > server max_id)
            server_max = server_max_ids.get((room_uuid, s_id))
            if last_id is not None and last_id > 0:
                if server_max is not None and last_id > server_max:
                    logging.warning(
                        f"[HISTORY_SYNC] Client watermark last_id={last_id} for RoomDBID:{r_id} Slot:{s_id} "
                        f"exceeds server max_id={server_max}. Resetting cursor for resync."
                    )
                    last_id = None

            if last_id is not None and last_id > 0:
                slot_filters.append(
                    (NotifiedItem.room_id == room_uuid) &
                    (NotifiedItem.receiving_slot_id == s_id) &
                    (NotifiedItem.id > last_id)
                )
            elif last_ts:
                try:
                    dt = datetime.fromisoformat(str(last_ts).replace('Z', '+00:00'))
                    if dt.tzinfo:
                        dt = dt.replace(tzinfo=None)
                    slot_filters.append(
                        (NotifiedItem.room_id == room_uuid) &
                        (NotifiedItem.receiving_slot_id == s_id) &
                        (NotifiedItem.timestamp > dt)
                    )
                except (ValueError, TypeError):
                    slot_filters.append(
                        (NotifiedItem.room_id == room_uuid) &
                        (NotifiedItem.receiving_slot_id == s_id)
                    )
            else:
                slot_filters.append(
                    (NotifiedItem.room_id == room_uuid) &
                    (NotifiedItem.receiving_slot_id == s_id)
                )

        if slot_filters:
            items = session.query(NotifiedItem).filter(or_(*slot_filters)).order_by(NotifiedItem.id.asc()).limit(200).all()


    hint_watermarks_map = {}
    for hint in data.get('hints', []):
        r_id = hint.get('room_db_id')
        last_upd = hint.get('last_updated')
        if r_id in room_db_id_to_uuid:
            hint_watermarks_map[r_id] = last_upd

    for r_id in room_db_id_to_uuid.keys():
        if r_id not in hint_watermarks_map:
            hint_watermarks_map[r_id] = None

    hints = []
    room_uuids = list(set(room_db_id_to_uuid.values()))
    if room_uuids:
        hint_filters = []
        for r_id, last_upd in hint_watermarks_map.items():
            room_uuid = room_db_id_to_uuid.get(r_id)
            if not room_uuid:
                continue
            if last_upd:
                try:
                    dt = datetime.fromisoformat(last_upd.replace('Z', '+00:00'))
                    if dt.tzinfo:
                        dt = dt.replace(tzinfo=None)
                    hint_filters.append(
                        (NotifiedHint.room_id == room_uuid) &
                        (NotifiedHint.updated_at > dt)
                    )
                except (ValueError, TypeError):
                    hint_filters.append(NotifiedHint.room_id == room_uuid)
            else:
                hint_filters.append(NotifiedHint.room_id == room_uuid)

        if hint_filters:
            hints = session.query(NotifiedHint).filter(or_(*hint_filters)).order_by(NotifiedHint.updated_at.asc()).limit(100).all()

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

    max_item_ids = {}
    for item in items:
        room_data = room_map_by_uuid.get(item.room_id)
        if room_data:
            key = f"{room_data.id}_{item.receiving_slot_id}"
            if key not in max_item_ids or item.id > max_item_ids[key]:
                max_item_ids[key] = item.id

    now_iso = format_iso_z(datetime.now(timezone.utc))

    new_item_watermarks = {}
    for (r_id, s_id) in tracked_set:
        key = f"{r_id}_{s_id}"
        if key in max_item_ids:
            new_item_watermarks[key] = max_item_ids[key]
        else:
            w_info = item_watermarks_map.get((r_id, s_id))
            last_id = w_info.get('last_id') if isinstance(w_info, dict) else None
            room_uuid = room_db_id_to_uuid.get(r_id)
            server_max = server_max_ids.get((room_uuid, s_id)) if room_uuid else None
            if last_id is not None and server_max is not None and last_id > server_max:
                last_id = server_max
            new_item_watermarks[key] = last_id if last_id is not None else 0


    max_hint_dts = {}
    for hint in hints:
        room_data = room_map_by_uuid.get(hint.room_id)
        if room_data:
            key = f"{room_data.id}"
            dt = hint.updated_at
            if dt:
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                if key not in max_hint_dts or dt > max_hint_dts[key]:
                    max_hint_dts[key] = dt

    new_hint_watermarks = {}
    for r_id in room_db_id_to_uuid.keys():
        key = f"{r_id}"
        if key in max_hint_dts:
            new_hint_watermarks[key] = format_iso_z(max_hint_dts[key])
        elif hint_watermarks_map.get(r_id):
            new_hint_watermarks[key] = hint_watermarks_map[r_id]
        else:
            new_hint_watermarks[key] = now_iso

    return jsonify({
        "new_items": response_items,
        "updated_hints": response_hints,
        "item_watermarks": new_item_watermarks,
        "hint_watermarks": new_hint_watermarks
    })

@history_bp.route('/history/items', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_global_item_history(current_user):
    session = Session()

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

    relevant_room_db_ids = list(slots_by_room_db_id.keys())
    
    room_objects = session.query(TrackedRoom).filter(TrackedRoom.id.in_(relevant_room_db_ids)).all()
    all_room_data = {r.room_id: r for r in room_objects}
    
    subs_query = session.query(UserRoomSubscription).filter(
        UserRoomSubscription.user_id == current_user.id,
        UserRoomSubscription.room_id.in_(relevant_room_db_ids)
    )
    subs_map = {sub.room_id: sub for sub in subs_query.all()}
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
                if not added_at_utc or added_at_utc > since_dt:
                    filters.append(
                        (NotifiedItem.room_id == room_uuid) &
                        (NotifiedItem.receiving_slot_id == slot_id)
                    )
                else:
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

    query = session.query(NotifiedItem).filter(or_(*filters)).order_by(NotifiedItem.id.desc())

    try:
        limit = max(1, min(int(request.args.get('limit', 50)), 100))
        offset = max(int(request.args.get('offset', 0)), 0)
    except (ValueError, TypeError):
        limit = 50
        offset = 0
    
    query = query.limit(limit).offset(offset)

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

    final_history_dicts = []
    items = query.all()

    if not items:
        return jsonify([])

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

@history_bp.route('/history/hints', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_global_hint_history(current_user):
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

@history_bp.route('/rooms/<int:room_db_id>/history/hints', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_room_hint_history(current_user, room_db_id):
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
