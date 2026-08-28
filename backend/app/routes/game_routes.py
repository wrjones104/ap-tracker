import logging
import json
import asyncio
import threading
from flask import Blueprint, request, jsonify
from sqlalchemy import func

from app import Session
from app.models import TrackedRoom, DatapackageCache
from app.utils import generate_negative_id
from app.routes.common import log_api_call, token_required, handle_db_errors

game_bp = Blueprint('game_routes', __name__)

_heal_locks = {}
_heal_global_lock = threading.Lock()

def rebuild_game_cache_synchronously(session, game_name):
    rooms = session.query(TrackedRoom).filter(
        TrackedRoom.game_checksums_json.isnot(None),
        TrackedRoom.game_checksums_json != '{}'
    ).all()
    
    checksum = None
    hostname = "archipelago.gg"
    target_room = None
    
    for r in rooms:
        try:
            checksums = json.loads(r.game_checksums_json)
            checksums_lower = {k.lower(): v for k, v in checksums.items()}
            if game_name.lower() in checksums_lower:
                checksum = checksums_lower[game_name.lower()]
                target_room = r
                if r.hostname:
                    hostname = r.hostname
                break
        except:
            pass
            
    if not checksum:
        checksum_row = session.query(DatapackageCache.checksum).filter(
            func.lower(DatapackageCache.game) == game_name.lower()
        ).first()
        if checksum_row:
            checksum = checksum_row[0]
            
    if not checksum:
        logging.warning(f"[SYNC_HEAL] Could not find checksum for game '{game_name}' to rebuild cache.")
        return False
        
    port = None
    if target_room and target_room.cached_full_address and ":" in target_room.cached_full_address:
        try:
            _, p_str = target_room.cached_full_address.split(":", 1)
            if p_str.isdigit():
                port = int(p_str)
        except:
            pass
            
    if not port and target_room:
        try:
            import requests
            resp = requests.get(f"https://{target_room.hostname}/api/room_status/{target_room.room_id}", timeout=5)
            if resp.status_code == 200:
                status_data = resp.json()
                port = status_data.get('last_port')
        except Exception as e:
            logging.warning(f"[SYNC_HEAL] Failed to fetch port from room status API: {e}")
            
    if not port:
        logging.warning(f"[SYNC_HEAL] Could not find port for game '{game_name}' to rebuild cache.")
        return False
        
    logging.info(f"[SYNC_HEAL] Fetching datapackage for '{game_name}' ({checksum}) via WebSocket from {hostname}:{port}...")
    
    async def fetch_datapackage_via_ws(hostname, port, target_room, checksum):
        import aiohttp
        import time
        from app.utils import SSRFProtectedTCPConnector
        
        uris = [f"wss://{hostname}:{port}", f"ws://{hostname}:{port}"]
        parts = hostname.split('.')
        if len(parts) > 2:
            base_domain = ".".join(parts[1:])
            uris.extend([f"wss://{base_domain}:{port}", f"ws://{base_domain}:{port}"])
            
        players = []
        if target_room and target_room.cached_players_json:
            try:
                players = json.loads(target_room.cached_players_json)
            except:
                pass
                
        tracker_player = None
        for p in players:
            if isinstance(p, dict) and p.get('game') and p.get('game') != 'Archipelago':
                tracker_player = p
                break
        if not tracker_player and players:
            tracker_player = players[0]
            
        ws_success = False
        game_data_res = None
        retrieved_res = {"item_name_groups": {}, "location_name_groups": {}}
        
        connector = None
        try:
            connector = SSRFProtectedTCPConnector()
        except:
            pass
            
        async with aiohttp.ClientSession(connector=connector) as client:
            for uri in uris:
                if ws_success:
                    break
                try:
                    async with client.ws_connect(uri, timeout=5) as ws:
                        msg = await ws.receive(timeout=5)
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                            
                        room_info_msg = json.loads(msg.data)
                        server_version = room_info_msg[0].get('version', {"major": 0, "minor": 4, "build": 4, "class": "Version"})
                        
                        authenticated = False
                        if tracker_player and isinstance(tracker_player, dict):
                            p_name = tracker_player.get('name')
                            p_game = tracker_player.get('game')
                            connect_packet = {
                                "cmd": "Connect",
                                "password": "",
                                "game": p_game,
                                "name": p_name,
                                "uuid": f"sync-heal-uuid-{target_room.room_id if target_room else 'unknown'}",
                                "tags": ["Tracker"],
                                "version": server_version,
                                "items_handling": 0
                            }
                            try:
                                await ws.send_json([connect_packet])
                                connect_timeout = 3.0
                                start_conn_time = time.time()
                                while time.time() - start_conn_time < connect_timeout:
                                    conn_msg = await ws.receive(timeout=1.0)
                                    if conn_msg.type == aiohttp.WSMsgType.TEXT:
                                        payload = json.loads(conn_msg.data)
                                        if isinstance(payload, list):
                                            connected_cmd = next((p for p in payload if p.get("cmd") == "Connected"), None)
                                            refused_cmd = next((p for p in payload if p.get("cmd") == "ConnectionRefused"), None)
                                            if connected_cmd:
                                                authenticated = True
                                                break
                                            elif refused_cmd:
                                                break
                                    elif conn_msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                        break
                            except Exception as conn_err:
                                logging.warning(f"[SYNC_HEAL] Handshake exception: {conn_err}")
                                
                        if authenticated:
                            await ws.send_json([{
                                "cmd": "Get",
                                "keys": [f"_read_item_name_groups_{game_name}", f"_read_location_name_groups_{game_name}"]
                            }])
                            
                        await ws.send_json([{"cmd": "GetDataPackage", "games": [game_name]}])
                        
                        start_recv_time = time.time()
                        timeout = 15
                        dp_received = False
                        
                        while time.time() - start_recv_time < timeout:
                            try:
                                ws_msg = await ws.receive(timeout=1.0)
                                if ws_msg.type == aiohttp.WSMsgType.TEXT:
                                    payload = json.loads(ws_msg.data)
                                    if isinstance(payload, list):
                                        for packet in payload:
                                            cmd = packet.get("cmd")
                                            if cmd == "Retrieved":
                                                keys_dict = packet.get("keys", {})
                                                item_key = f"_read_item_name_groups_{game_name}"
                                                loc_key = f"_read_location_name_groups_{game_name}"
                                                if item_key in keys_dict and isinstance(keys_dict[item_key], dict):
                                                    retrieved_res["item_name_groups"] = keys_dict[item_key]
                                                if loc_key in keys_dict and isinstance(keys_dict[loc_key], dict):
                                                    retrieved_res["location_name_groups"] = keys_dict[loc_key]
                                            elif cmd == "DataPackage":
                                                dp_data = packet.get("data") or packet.get("datapackage")
                                                actual_datapackage = dp_data.get("games") if isinstance(dp_data, dict) else {}
                                                if isinstance(actual_datapackage, dict):
                                                    matched_game = next((g for g in actual_datapackage.keys() if g.lower() == game_name.lower()), None)
                                                    if matched_game:
                                                        game_data_res = actual_datapackage[matched_game]
                                                        dp_received = True
                                elif ws_msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                    break
                            except asyncio.TimeoutError:
                                pass
                                
                            if dp_received:
                                ws_success = True
                                break
                except Exception as ws_ex:
                    logging.warning(f"[SYNC_HEAL] WebSocket failed for {uri}: {ws_ex}")
                    
        if game_data_res and isinstance(game_data_res, dict):
            if retrieved_res["item_name_groups"]:
                game_data_res["item_name_groups"] = retrieved_res["item_name_groups"]
            if retrieved_res["location_name_groups"]:
                game_data_res["location_name_groups"] = retrieved_res["location_name_groups"]
            return game_data_res
        return None

    actual_data = None
    try:
        actual_data = asyncio.run(fetch_datapackage_via_ws(hostname, port, target_room, checksum))
    except Exception as e:
        logging.error(f"[SYNC_HEAL] Exception fetching datapackage: {e}")
        
    if not actual_data:
        return False
        
    try:
        session.query(DatapackageCache).filter_by(checksum=checksum).delete()
        current_game_entries = []
        seen_ids = set()

        for n, eid in actual_data.get('item_name_to_id', {}).items():
            if ('item', eid) in seen_ids: continue
            seen_ids.add(('item', eid))
            current_game_entries.append(DatapackageCache(
                game=game_name, checksum=checksum, entity_type='item', entity_id=eid, entity_name=n
            ))

        for n, eid in actual_data.get('location_name_to_id', {}).items():
            if ('location', eid) in seen_ids: continue
            seen_ids.add(('location', eid))
            current_game_entries.append(DatapackageCache(
                game=game_name, checksum=checksum, entity_type='location', entity_id=eid, entity_name=n
            ))

        for g_name, g_items in actual_data.get('item_name_groups', {}).items():
            g_id = generate_negative_id('item_group', g_name)
            current_game_entries.append(DatapackageCache(
                game=game_name, checksum=checksum, entity_type='item_group', entity_id=g_id, entity_name=g_name
            ))
            
        item_groups = actual_data.get('item_name_groups', {})
        if item_groups:
            current_game_entries.append(DatapackageCache(
                game=game_name, checksum=checksum, entity_type='item_name_groups_json', entity_id=0, entity_name=json.dumps(item_groups)
            ))

        for g_name, g_locations in actual_data.get('location_name_groups', {}).items():
            g_id = generate_negative_id('location_group', g_name)
            current_game_entries.append(DatapackageCache(
                game=game_name, checksum=checksum, entity_type='location_group', entity_id=g_id, entity_name=g_name
            ))
            
        loc_groups = actual_data.get('location_name_groups', {})
        if loc_groups:
            current_game_entries.append(DatapackageCache(
                game=game_name, checksum=checksum, entity_type='location_name_groups_json', entity_id=0, entity_name=json.dumps(loc_groups)
            ))

        if not current_game_entries:
            current_game_entries.append(DatapackageCache(
                game=game_name, checksum=checksum, entity_type='_metadata', entity_id=0, entity_name='_empty_datapackage'
            ))
        else:
            current_game_entries.append(DatapackageCache(
                game=game_name, checksum=checksum, entity_type='_metadata', entity_id=0, entity_name='_completed_v2'
            ))

        session.bulk_save_objects(current_game_entries)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        logging.error(f"[SYNC_HEAL] Error rebuilding cache for '{game_name}': {e}", exc_info=True)
        return False

def heal_datapackage_cache_if_outdated(session, game_name):
    if not game_name:
        return

    game_key = game_name.lower()
    with _heal_global_lock:
        if game_key not in _heal_locks:
            _heal_locks[game_key] = threading.Lock()
        game_lock = _heal_locks[game_key]

    with game_lock:
        try:
            old_checksums = [c[0] for c in session.query(DatapackageCache.checksum).filter(
                func.lower(DatapackageCache.game) == game_key,
                DatapackageCache.entity_type == '_metadata',
                DatapackageCache.entity_name == '_completed'
            ).all() if c and c[0]]

            if old_checksums:
                session.query(DatapackageCache).filter(
                    DatapackageCache.checksum.in_(old_checksums),
                    DatapackageCache.entity_type == '_metadata',
                    DatapackageCache.entity_name == '_completed'
                ).delete(synchronize_session=False)
                session.commit()
                rebuild_game_cache_synchronously(session, game_name)
                return
                
            json_query = session.query(DatapackageCache.checksum).filter(
                func.lower(DatapackageCache.game) == game_key,
                DatapackageCache.entity_type == 'item_name_groups_json'
            )
            
            bad_checksums = [c[0] for c in session.query(DatapackageCache.checksum).filter(
                func.lower(DatapackageCache.game) == game_key,
                DatapackageCache.entity_type == 'item_group',
                ~DatapackageCache.checksum.in_(json_query)
            ).distinct().all() if c and c[0]]
            
            if bad_checksums:
                session.query(DatapackageCache).filter(
                    DatapackageCache.checksum.in_(bad_checksums),
                    DatapackageCache.entity_type == 'item_group'
                ).delete(synchronize_session=False)
                session.commit()
                rebuild_game_cache_synchronously(session, game_name)
        except Exception as e:
            session.rollback()
            logging.error(f"[SELF_HEALING] Error during cache healing check: {e}", exc_info=True)

@game_bp.route('/games', methods=['GET'])
@log_api_call
def get_games():
    session = Session()
    try:
        games = session.query(DatapackageCache.game).distinct().order_by(DatapackageCache.game).all()
        game_list = [g[0] for g in games if g[0]]
        return jsonify(game_list)
    finally:
        Session.remove()

@game_bp.route('/games/<path:game_name>/items', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_game_available_items(current_user, game_name):
    session = Session()
    try:
        items_query = session.query(DatapackageCache.entity_name, DatapackageCache.entity_type).filter(
            DatapackageCache.game == game_name,
            DatapackageCache.entity_type.in_(['item', 'item_group'])
        ).distinct().all()
        
        if not items_query:
            items_query = session.query(DatapackageCache.entity_name, DatapackageCache.entity_type).filter(
                func.lower(DatapackageCache.game) == game_name.lower(),
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

@game_bp.route('/games/<path:game_name>/items/<path:item_name>/groups', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_item_groups(current_user, game_name, item_name):
    session = Session()
    try:
        heal_datapackage_cache_if_outdated(session, game_name)
        checksum = request.args.get('checksum') or request.args.get('datapackage_checksum')
        if not checksum:
            room_db_id = request.args.get('room_db_id')
            if room_db_id:
                try:
                    room = session.query(TrackedRoom.game_checksums_json).filter_by(id=int(room_db_id)).first()
                    if room and room[0]:
                        checksums = json.loads(room[0])
                        if isinstance(checksums, dict):
                            checksum = checksums.get(game_name)
                            if not checksum:
                                game_name_lower = game_name.lower()
                                checksum = next(
                                    (v for k, v in checksums.items()
                                     if isinstance(k, str) and k.lower() == game_name_lower),
                                    None
                                )
                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    logging.warning(f"[API] Failed to parse room game_checksums_json for room_db_id {room_db_id}: {e}")

        if not checksum:
            checksum_row = session.query(DatapackageCache.checksum).filter(
                DatapackageCache.game == game_name
            ).first()
            if not checksum_row:
                checksum_row = session.query(DatapackageCache.checksum).filter(
                    func.lower(DatapackageCache.game) == game_name.lower()
                ).first()
            if checksum_row:
                checksum = checksum_row[0]

        if not checksum:
            return jsonify([])
        
        groups_json_row = session.query(DatapackageCache.entity_name).filter(
            DatapackageCache.checksum == checksum,
            DatapackageCache.entity_type == 'item_name_groups_json'
        ).first()
        
        groups = set()
        if groups_json_row and groups_json_row[0]:
            try:
                groups_dict = json.loads(groups_json_row[0])
                if isinstance(groups_dict, dict):
                    for g_name, items in groups_dict.items():
                        if isinstance(items, list):
                            if any(item.lower() == item_name.lower() for item in items):
                                groups.add(g_name)
            except Exception:
                pass
        else:
            members = session.query(DatapackageCache.entity_name).filter(
                DatapackageCache.checksum == checksum,
                DatapackageCache.entity_type == 'item_group_member'
            ).all()
            for (member_key,) in members:
                try:
                    parsed = json.loads(member_key)
                    if isinstance(parsed, list) and len(parsed) == 2:
                        g_name, item = parsed
                        if item.lower() == item_name.lower():
                            groups.add(g_name)
                except Exception:
                    if ':' in member_key:
                        parts = member_key.split(':', 1)
                        if parts[1].lower() == item_name.lower():
                            groups.add(parts[0])
                    
        sorted_groups = sorted(list(groups))
        return jsonify(sorted_groups)
    finally:
        Session.remove()

@game_bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/items', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_slot_available_items(current_user, room_db_id, slot_id):
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
            return jsonify({'error': f'Slot {slot_id} not found in room info cache'}), 404
            
        game = slot_info.get('game')
        if not game:
            return jsonify([])
            
        heal_datapackage_cache_if_outdated(session, game)
            
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

@game_bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/locations', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_slot_available_locations(current_user, room_db_id, slot_id):
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
            return jsonify({'error': f'Slot {slot_id} not found in room info cache'}), 404
            
        game = slot_info.get('game')
        if not game:
            return jsonify([])
            
        heal_datapackage_cache_if_outdated(session, game)
            
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


@game_bp.route('/datapackage/checksum/<string:checksum>', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_datapackage_by_checksum(current_user, checksum):
    """
    Serve one game's id -> name tables, addressed by its Archipelago datapackage checksum.

    A checksum is a content hash: the same checksum always describes exactly the same
    item and location tables, forever. That makes this response immutable, so clients
    store it on disk and never revalidate it. Room-scoped facts (player names, which
    slot plays which game) are deliberately not included -- they change whenever
    somebody joins or sets an alias, and folding them in here would make the whole
    payload uncacheable. Clients read those from the Archipelago handshake instead.

    Only 'item' and 'location' rows are served. Group rows carry synthetic negative ids
    from generate_negative_id() which can collide with real negative ids -- Archipelago's
    generic world uses location -1 and -2 -- and PrintJSON never refers to a group by id,
    so including them could only corrupt a lookup.
    """
    session = Session()
    try:
        # The checksum comes straight off the wire from RoomInfo, so reject anything
        # that cannot be one before it reaches the database.
        if not checksum or len(checksum) > 128:
            return jsonify({'error': 'Invalid checksum'}), 400

        rows = session.query(
            DatapackageCache.entity_type,
            DatapackageCache.entity_id,
            DatapackageCache.entity_name,
            DatapackageCache.game
        ).filter(
            DatapackageCache.checksum == checksum,
            DatapackageCache.entity_type.in_(['item', 'location', '_metadata'])
        ).all()

        if not rows:
            logging.info(f"[DATAPACKAGE] 404: checksum {checksum} not cached.")
            return jsonify({'error': 'Datapackage not cached for this checksum'}), 404

        items = {}
        locations = {}
        game = None
        for entity_type, entity_id, entity_name, row_game in rows:
            if game is None:
                game = row_game
            if entity_type == 'item':
                items[str(entity_id)] = entity_name
            elif entity_type == 'location':
                locations[str(entity_id)] = entity_name

        # A game with a genuinely empty datapackage caches only its _metadata marker.
        # Answering 200-with-nothing lets the client record "nothing to resolve here"
        # permanently; a 404 would send it back to re-ask on every connect.
        response = jsonify({
            'checksum': checksum,
            'game': game,
            'items': items,
            'locations': locations,
        })
        # Private, not public: the body is not user-specific but the route is
        # authenticated, so shared caches must not retain it.
        response.headers['Cache-Control'] = 'private, max-age=31536000, immutable'
        response.set_etag(checksum)
        return response.make_conditional(request)
    finally:
        Session.remove()
