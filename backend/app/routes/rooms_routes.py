import logging
import json
import os
import socket
import asyncio
from datetime import datetime, timedelta
from typing import cast
from urllib.parse import urlparse
from ipaddress import ip_address

from flask import Blueprint, request, jsonify, current_app

from app import Session
from app.models import TrackedRoom, UserRoomSubscription, UserTrackedSlot, DatapackageCache
from app.utils import (
    verify_ap_server, get_web_base_url, parse_cached_checks, normalize_track_mode
)
from app.routes.common import log_api_call, token_required, handle_db_errors
from app.routes.slots_routes import build_cheese_claim_summary

from sqlalchemy import func

rooms_bp = Blueprint('rooms_routes', __name__)

@rooms_bp.route('/rooms', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_rooms(current_user):
    show_archived_str = request.args.get('archived', 'false')
    show_archived = show_archived_str.lower() in ['true', '1', 't', 'yes']

    session = Session()
    
    subscriptions = session.query(UserRoomSubscription).join(TrackedRoom).filter(
        UserRoomSubscription.user_id == current_user.id,
        UserRoomSubscription.is_archived == show_archived, 
        ~TrackedRoom.room_id.startswith("PENDING_DISCOVERY") 
    ).all()
    
    # Pre-aggregate slot counts per room to eliminate N+1 SQL query bottleneck
    slot_counts_query = session.query(
        UserTrackedSlot.room_id,
        func.count(UserTrackedSlot.id)
    ).filter(
        UserTrackedSlot.user_id == current_user.id
    ).group_by(UserTrackedSlot.room_id).all()
    
    slot_counts = {r_id: count for r_id, count in slot_counts_query}

    rooms_list = []
    for sub in subscriptions:
        room = sub.room
        if room.room_id.startswith("PENDING_DISCOVERY"):
            continue

        tracked_count = slot_counts.get(room.id, 0)
        
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
            'tracked_slots_count': tracked_count,
            'web_url': f"{get_web_base_url(room.hostname)}/room/{room.room_id}"
        })

    return jsonify(rooms_list)

@rooms_bp.route('/rooms', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def add_room(current_user):
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
                try:
                    resolved_ip = socket.gethostbyname(first_part)
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
        room_id = parsed_url.path.strip('/').split('/')[-1]
    except Exception as e:
        return jsonify({'error': f'Invalid room_url: {e}'}), 400

    if not hostname or not room_id:
        return jsonify({'error': 'Could not parse hostname or room_id from URL'}), 400

    session = Session()
    room = session.query(TrackedRoom).filter_by(room_id=room_id).first()
    ap_tracker_id = None

    if not room:
        logging.info(f"[API] First time seeing room {room_id}. Creating global record.")
        try:
            async def _verify_and_cleanup():
                try:
                    return await verify_ap_server(hostname, room_id)
                finally:
                    await asyncio.sleep(0.05)

            room_data = asyncio.run(_verify_and_cleanup())
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
            from app.api_cheese import push_new_room_to_cheese
            import threading
            
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

@rooms_bp.route('/rooms/<int:room_db_id>/revive', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def revive_room(current_user, room_db_id):
    session = Session()
    subscription = session.query(UserRoomSubscription).filter_by(
        user_id=current_user.id,
        room_id=room_db_id
    ).first()

    if not subscription:
        return jsonify({'error': 'Not subscribed to this room'}), 403

    room = subscription.room
    if not room:
        return jsonify({'error': 'Room not found'}), 404

    if room.is_complete:
        return jsonify({'error': 'Cannot revive a completed room.'}), 400

    if not room.is_suspended:
        return jsonify({'error': 'Room is not suspended.'}), 400

    now_time = datetime.utcnow()
    if room.last_revive_attempt:
        if now_time - room.last_revive_attempt < timedelta(seconds=30):
            logging.warning(f"[API_RATE_LIMIT] User {current_user.id} spammed revive for Room {room.id}.")
            return jsonify({'error': 'Please wait 30 seconds between revival attempts.'}), 429

    logging.info(f"[API] Reviving suspended room {room.id} because User {current_user.id} requested it.")
    try:
        room.is_suspended = False
        room.failed_poll_count = 0
        room.needs_immediate_poll = True
        room.last_revive_attempt = now_time
        session.commit()
    except Exception as e:
        session.rollback()
        logging.error(f"[API_ERROR] Database commit failed when reviving Room {room.id}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to update room status in database.'}), 500

    return jsonify({'message': 'Room revived successfully.'}), 200

@rooms_bp.route('/rooms/<int:room_db_id>', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_subscription(current_user, room_db_id):
    data = request.json or {}
    alias = data.get('alias')
    icon_name = data.get('icon_name')
    is_archived = data.get('is_archived') 

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

@rooms_bp.route('/rooms/<int:room_db_id>', methods=['DELETE'])
@handle_db_errors
@log_api_call
@token_required
def unsubscribe_from_room(current_user, room_db_id):
    session = Session()
    subscription = session.query(UserRoomSubscription).filter_by(
        user_id=current_user.id,
        room_id=room_db_id
    ).first()

    if not subscription:
        return jsonify({'error': 'Not subscribed to this room'}), 404

    cheese_tracker_id = None
    if subscription.room:
        cheese_tracker_id = subscription.room.cheese_tracker_id

    session.delete(subscription)
    session.commit()
    logging.info(f"[API] User {current_user.id} unsubscribed from room {room_db_id}")

    if current_user.cheese_api_key and cheese_tracker_id:
        try:
            from app.api_cheese import update_tracker_visibility
            import threading
            
            app_context = current_app._get_current_object()
            threading.Thread(
                target=update_tracker_visibility,
                args=(app_context, current_user.id, cheese_tracker_id, False)
            ).start()
        except Exception as e:
            logging.error(f"[API_ERROR] Failed to start Cheese visibility thread: {e}", exc_info=True)

    return jsonify({'message': 'Successfully unsubscribed from room.'})

@rooms_bp.route('/rooms/<int:room_db_id>/players', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_room_players(current_user, room_db_id):
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

        checks_map = parse_cached_checks(room.cached_checks_json)
        # None (JSON null) means "counts never fetched for this room", which is
        # distinct from False. Clients must treat null as unknown and fall back
        # to goal-only rather than reporting the slot as unfinished.
        checks_known = bool(checks_map)

        tracked_slots_query = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id,
            room_id=room_db_id
        ).all()

        tracked_slots_map = {ts.slot_id: ts for ts in tracked_slots_query}

        # Per-slot Cheese claim state, read from the room's cached tracker JSON
        # so the picker can pre-resolve claims without any extra Cheese calls.
        # Built for anyone with a Cheese key; callers without one see
        # `cheese_claim: null` and the plain checkbox.
        cheese_games_map = {}
        user_has_cheese = bool(current_user.cheese_api_key)
        if user_has_cheese and room.cheese_tracker_id and room.cached_cheese_json:
            try:
                cheese_data = json.loads(room.cached_cheese_json)
                if isinstance(cheese_data, dict):
                    for g in cheese_data.get('games', []):
                        pos = g.get('position')
                        if pos is not None:
                            cheese_games_map[pos] = g
            except (json.JSONDecodeError, TypeError):
                cheese_games_map = {}

        my_discord_clean = current_user.discord_username.strip().lower() if current_user.discord_username else None

        response_players = []
        for p in players_list:
            slot_id = p.get('slot_id')
            try:
                slot_id_int = int(slot_id) if slot_id is not None else None
            except (ValueError, TypeError):
                slot_id_int = None
            
            tracked_slot_entry = tracked_slots_map.get(slot_id_int) if slot_id_int is not None else None
            is_tracked = tracked_slot_entry is not None

            # A fresh room has no tracker id and no cached JSON yet -- it gets
            # linked on the next sync -- and gating on those hid the
            # Playing/Watching choice at exactly the moment the user was first
            # deciding what to track. An absent game resolves to "nothing holds
            # this, you may claim it", which is the truth for an unlinked room.
            # See #314.
            cheese_claim = None
            if user_has_cheese:
                cheese_game = cheese_games_map.get(slot_id_int) if slot_id_int is not None else None
                cheese_claim = build_cheese_claim_summary(
                    cheese_game or {},
                    current_user.cheese_user_id,
                    my_discord_clean
                )

            response_players.append({
                'slot_id': slot_id_int if slot_id_int is not None else slot_id,
                'name': p.get('name'),
                'alias': p.get('alias'),
                'game': p.get('game'),
                # is_finished stays goal-only on the wire so older app builds keep
                # their existing behavior. Clients that understand the newer facts
                # evaluate the user's chosen definition themselves.
                'is_finished': p.get('is_finished', False),
                'has_all_checks': p.get('has_all_checks', False) if checks_known else None,
                'checks_done': checks_map.get(slot_id_int) if checks_known else None,
                'total_locations': p.get('total_locations', 0),
                'is_tracked': is_tracked,
                'track_mode': normalize_track_mode(tracked_slot_entry.track_mode) if tracked_slot_entry else None,
                'cheese_claim': cheese_claim,
                'needs_backfill': tracked_slot_entry.needs_backfill if tracked_slot_entry else False,
                'notify_progression': tracked_slot_entry.notify_progression if tracked_slot_entry else None,
                'notify_useful': tracked_slot_entry.notify_useful if tracked_slot_entry else None,
                'notify_filler': tracked_slot_entry.notify_filler if tracked_slot_entry else None,
                'notify_trap': tracked_slot_entry.notify_trap if tracked_slot_entry else None,
                'notify_hints': tracked_slot_entry.notify_hints if tracked_slot_entry else None
            })
        
        return jsonify(response_players)
    finally:
        Session.remove()

@rooms_bp.route('/rooms/<int:room_db_id>/datapackage', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_room_datapackage(current_user, room_db_id):
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
        if not room:
            logging.warning(f"[DATAPACKAGE] 404: Room {room_db_id} not found in DB.")
            return jsonify({'error': 'Room not found'}), 404

        try:
            players_json = json.loads(room.cached_players_json or '[]')
            game_checksums = json.loads(room.game_checksums_json or '{}')
        except (json.JSONDecodeError, TypeError):
            players_json = []
            game_checksums = {}

        player_map = {str(p['slot_id']): (p.get('alias') or p.get('name') or f"Player {p['slot_id']}") for p in players_json if 'slot_id' in p}
        player_map["0"] = "Archipelago"

        items_map = {}
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

        return jsonify({
            'players': player_map,
            'items': items_map,
            # No item_flags here: in Archipelago, flags are a property of an item
            # *instance* (NetworkItem.flags), not of an item type, so the
            # datapackage cannot carry them. PrintJSON segments supply them.
            'locations': locations_map,
            'slot_to_checksum': slot_to_checksum,
            # Archipelago's generic world. Its ids -- location -1 is Cheat Console,
            # -2 is Server -- are valid inside every game, so a client resolving an
            # id needs to know which checksum to fall back to. Without this, clients
            # on this route render those as raw numbers.
            'generic_checksum': game_checksums.get('Archipelago')
        })
    finally:
        Session.remove()
