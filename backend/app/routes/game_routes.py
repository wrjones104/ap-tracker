import logging
import json
import threading
import time
from flask import Blueprint, request, jsonify
from sqlalchemy import text

from app import Session
from app.models import TrackedRoom, DatapackageCache
from app.routes.common import log_api_call, token_required, handle_db_errors

game_bp = Blueprint('game_routes', __name__)

# Postgres has no loose index scan, so a plain DISTINCT over game reads one
# index entry per cached row: 13 M entries and 14.8 s on prod to return ~2,400
# names. This walks the same index one game at a time instead -- each step asks
# for the first game after the last one -- so the cost follows the number of
# games, not the size of the table. See #439.
_DISTINCT_GAMES_SQL = text("""
    WITH RECURSIVE games(game) AS (
        SELECT MIN(game) FROM datapackage_cache
        UNION ALL
        SELECT (SELECT MIN(d.game) FROM datapackage_cache d WHERE d.game > games.game)
        FROM games
        WHERE games.game IS NOT NULL
    )
    SELECT game FROM games WHERE game IS NOT NULL ORDER BY game
""")

# The list only grows when the poller caches a game new to the whole server,
# and the app already holds it for the session, so a few minutes of staleness
# costs nothing. Process memory is enough: the API runs as one process.
_GAMES_CACHE_TTL_SECONDS = 300
_games_cache = {'games': None, 'expires_at': 0.0}
_games_cache_lock = threading.Lock()


def _known_games():
    now = time.monotonic()
    cached = _games_cache['games']
    if cached is not None and now < _games_cache['expires_at']:
        return cached
    # One thread refreshes; the rest wait for its answer rather than each
    # running the query.
    with _games_cache_lock:
        if _games_cache['games'] is not None and time.monotonic() < _games_cache['expires_at']:
            return _games_cache['games']
        session = Session()
        try:
            rows = session.execute(_DISTINCT_GAMES_SQL).all()
        finally:
            Session.remove()
        games = [r[0] for r in rows if r[0]]
        _games_cache['games'] = games
        _games_cache['expires_at'] = time.monotonic() + _GAMES_CACHE_TTL_SECONDS
        return games


@game_bp.route('/games', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_games(current_user):
    return jsonify(_known_games())

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

        # Exact match only. A lower(game) fallback here was a full scan of
        # datapackage_cache on every miss (34 s on prod), and the app only ever
        # sends names it got from the server verbatim. See #407.
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
            # Exact match only, as in get_game_available_items (#407).
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
