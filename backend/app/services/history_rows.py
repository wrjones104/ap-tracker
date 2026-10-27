"""
The item and hint rows the app stores, built from the database the one way both of their
senders use: `POST /history/sync`, and the item payload a push carries (#416).

Moved here unchanged from the sync route so the two cannot drift apart. A row the app stores
from a push must be the row it would have downloaded, or a later download would not replace
it and the two copies would disagree.
"""
import json

from sqlalchemy import tuple_
from sqlalchemy.orm import selectinload

from app.models import User, DatapackageCache, SlotItemCount
from app.routes.common import format_iso_z, chunked_iterable
from app.utils import parse_cached_checks
from app.services.filtering_service import fetch_group_members_lookup, evaluate_item_filter_status

# Postgres rejects a statement carrying more than 65535 bind parameters. This
# lookup binds three per key, so the IN list is chunked well below that ceiling.
DATAPACKAGE_LOOKUP_CHUNK_SIZE = 1000


def fetch_datapackage_names(session, cache_keys):
    """Resolves (checksum, entity_type, entity_id) keys to their entity names."""
    name_cache_map = {}
    for chunk in chunked_iterable(cache_keys, DATAPACKAGE_LOOKUP_CHUNK_SIZE):
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
            ).in_(chunk)
        )
        for c in cache_query.all():
            name_cache_map[(c.checksum, c.entity_type, c.entity_id)] = c.entity_name
    return name_cache_map


def serialize_history_rows(session, user_id, items, hints, room_map_by_uuid, room_uuid_to_sub):
    """
    `items` (NotifiedItem) and `hints` (NotifiedHint) as the app stores them, for `user_id`,
    whose ignore and whitelist rules decide each row's flags. `room_map_by_uuid` and
    `room_uuid_to_sub` map a room's uuid to its TrackedRoom and the user's subscription; a row
    whose room is missing from either is left out.

    Returns (items, hints), each a list of dicts in the shape /history/sync sends.
    """
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
                'checks_known': bool(parse_cached_checks(room_data.cached_checks_json)),
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

    name_cache_map = fetch_datapackage_names(session, cache_keys_to_find)

    filter_checksums = set()
    for item in items:
        meta = parsed_room_metadata.get(item.room_id, {})
        receiver_game = meta.get('game_map', {}).get(item.receiving_slot_id, "Unknown")
        rec_checksum = meta.get('game_checksums', {}).get(receiver_game)
        if rec_checksum:
            filter_checksums.add(rec_checksum)
    for hint in hints:
        meta = parsed_room_metadata.get(hint.room_id, {})
        io_game = meta.get('game_map', {}).get(hint.item_owner_id, "Unknown")
        io_checksum = meta.get('game_checksums', {}).get(io_game)
        if io_checksum:
            filter_checksums.add(io_checksum)

    group_members_lookup = fetch_group_members_lookup(session, filter_checksums)
    # Re-queried: the caller's user object may be detached (token_required expunges it).
    prefs_user = session.query(User).options(
        selectinload(User.ignore_items), selectinload(User.whitelist_items)
    ).filter_by(id=user_id).first()
    ignore_items = prefs_user.ignore_items if prefs_user else []
    whitelist_items = prefs_user.whitelist_items if prefs_user else []

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
        # None means "counts never fetched for this room", which is categorically
        # different from False and makes every definition fall back to goal-only.
        # Emitting False there would report goaled slots as still sending.
        has_all_checks = (receiver_obj.get('has_all_checks', False) if receiver_obj else False) \
            if meta.get('checks_known') else None

        rec_checksum = game_checksums.get(receiver_game)
        snd_checksum = game_checksums.get(sender_game)

        item_name = name_cache_map.get((rec_checksum, 'item', item.item_id)) or f"Item ID {item.item_id}"
        location_name = name_cache_map.get((snd_checksum, 'location', item.location_id)) or f"Location ID {item.location_id}"

        is_ignored, is_whitelisted, _, _ = evaluate_item_filter_status(
            item_name=item_name,
            game_name=receiver_game,
            game_checksum=rec_checksum,
            ignore_items=ignore_items,
            whitelist_items=whitelist_items,
            group_members_lookup=group_members_lookup
        )

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
            "playerHasAllChecks": has_all_checks,
            "itemFlags": item.item_flags or 0,
            "timestamp": format_iso_z(item.timestamp),
            "tracker_id": room_data.tracker_id,
            "slot_id": receiver_id,
            "host": room_data.hostname,
            "receivedCount": item_counts.get((item.room_id, item.receiving_slot_id, item.item_id), 0),
            "isIgnored": is_ignored,
            "isWhitelisted": is_whitelisted
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

        is_ignored, is_whitelisted, _, _ = evaluate_item_filter_status(
            item_name=item_name,
            game_name=io_game,
            game_checksum=io_checksum,
            ignore_items=ignore_items,
            whitelist_items=whitelist_items,
            group_members_lookup=group_members_lookup
        )

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
            "item_flags": hint.item_flags or 0,
            "isIgnored": is_ignored,
            "isWhitelisted": is_whitelisted
        })

    return response_items, response_hints
