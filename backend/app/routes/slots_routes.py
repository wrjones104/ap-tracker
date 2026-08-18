import logging
import json
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.orm import selectinload
from sqlalchemy import func as sa_func

from app import Session
from app.models import (
    User, TrackedRoom, UserRoomSubscription, UserTrackedSlot,
    UserIgnoreItem, UserWhitelistItem, NotifiedItem
)
from app.routes.common import log_api_call, token_required, handle_db_errors, format_iso_z
from app.utils import parse_cached_checks, VALID_FINISHED_DEFINITIONS

slots_bp = Blueprint('slots_routes', __name__)

# Valid Cheese Tracker enum wire values (from CT's db/model.rs). Used to build
# and validate the per-slot Cheese state.
VALID_CHEESE_PROGRESSION = {'unknown', 'unblocked', 'bk', 'soft_bk', 'go'}
VALID_CHEESE_COMPLETION = {'incomplete', 'all_checks', 'goal', 'done', 'released'}
VALID_CHEESE_PING = {'liberally', 'sparingly', 'hints', 'see_notes', 'never'}
# Progression statuses that represent "beatable but blocked" and, per CT's web
# UI, stamp last_checked when set (enabling the "Still BK" behavior).
CHEESE_BK_STATUSES = {'bk', 'soft_bk'}


def game_is_owned_by(game, cheese_user_id, discord_username_clean):
    """
    Determines whether a Cheese game object is claimed by the given user.
    Mirrors the ownership logic in api_cheese.send_state: prefer the
    authenticated ct_user_id, fall back to an unauthenticated discord-name match.
    """
    remote_owner_id = game.get('claimed_by_ct_user_id')
    if remote_owner_id is not None:
        return cheese_user_id is not None and remote_owner_id == cheese_user_id

    claim_discord = game.get('effective_discord_username') or game.get('discord_username')
    claim_discord_clean = claim_discord.strip().lower() if claim_discord else None
    if claim_discord_clean is None:
        return False
    return discord_username_clean is not None and claim_discord_clean == discord_username_clean


def build_cheese_slot_state(game, global_ping_policy, cheese_user_id, discord_username_clean):
    """Builds the per-slot Cheese sub-object attached to a tracked slot."""
    return {
        'game_id': game.get('id'),
        'notes': game.get('notes') or '',
        'progression_status': game.get('progression_status'),
        'completion_status': game.get('completion_status'),
        'discord_ping': game.get('discord_ping'),
        'last_checked': game.get('last_checked'),
        'last_activity': game.get('last_activity'),
        'is_mine': game_is_owned_by(game, cheese_user_id, discord_username_clean),
        'global_ping_policy': global_ping_policy,
    }

@slots_bp.route('/rooms/<int:room_db_id>/slots', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_tracked_slots(current_user, room_db_id):
    data = request.json or {}
    if 'tracked_slot_ids' not in data or not isinstance(data['tracked_slot_ids'], list):
        return jsonify({'error': 'Missing or invalid tracked_slot_ids'}), 400

    session = Session()
    subscription = session.query(UserRoomSubscription).filter_by(
        user_id=current_user.id,
        room_id=room_db_id
    ).first()
    if not subscription:
        return jsonify({'error': 'You are not subscribed to this room'}), 403

    raw_requested_ids = data.get('tracked_slot_ids', [])
    requested_ids = set()
    for sid in raw_requested_ids:
        try:
            requested_ids.add(int(sid))
        except (ValueError, TypeError):
            pass

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
            UserTrackedSlot(
                user_id=current_user.id, 
                room_id=room_db_id, 
                slot_id=slot_id,
                added_at=datetime.utcnow()
            )
            for slot_id in slots_to_add if isinstance(slot_id, int) and slot_id > 0
        ]
        session.bulk_save_objects(objects_to_add)
        logging.info(f"[API] User {current_user.id} tracked {len(objects_to_add)} new slots in room {room_db_id}.")

    session.commit()

    if slots_to_add:
        try:
            from app.poller import trigger_immediate_room_poll
            trigger_immediate_room_poll(room_db_id)
        except Exception as e:
            logging.error(f"[API_ERROR] Failed to trigger immediate room poll: {e}", exc_info=True)

    if current_user.cheese_api_key and (slots_to_add or slots_to_remove):
        try:
            import threading
            from app.api_cheese import push_slot_changes_to_cheese
            app_context = current_app._get_current_object()
            threading.Thread(target=push_slot_changes_to_cheese, args=(
                app_context, 
                current_user.id,
                room_db_id, 
                slots_to_add, 
                slots_to_remove
            )).start()
        except Exception as e:
            logging.error(f"[API_ERROR] Failed to trigger Cheese push thread: {e}", exc_info=True)

    return jsonify({'message': 'Tracked slots updated.'})

@slots_bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/preferences', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_slot_preferences(current_user, room_db_id, slot_id):
    data = request.json or {}
    session = Session()
    try:
        slot = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id,
            room_id=room_db_id,
            slot_id=slot_id
        ).first()

        if not slot:
            return jsonify({'error': 'Tracked slot not found'}), 404

        for field in [
            'notify_progression', 'notify_useful', 'notify_filler', 'notify_trap',
            'notify_hints', 'notify_hints_remote_items', 'notify_finished',
            'use_condensed_messages', 'combine_notifications', 'suppress_own_events',
            'remove_emojis', 'suppress_self_found', 'suppress_connected'
        ]:
            if field in data:
                val = data[field]
                setattr(slot, field, bool(val) if val is not None else None)

        # Handled separately: the loop above coerces with bool(), which would
        # turn any non-empty definition string into True.
        if 'finished_definition' in data:
            val = data['finished_definition']
            if val is None:
                slot.finished_definition = None
            elif val in VALID_FINISHED_DEFINITIONS:
                slot.finished_definition = val
            else:
                return jsonify({'error': 'Invalid finished_definition.'}), 400

        session.commit()
        return jsonify({'message': 'Slot preferences updated successfully'}), 200
    except Exception as e:
        session.rollback()
        logging.error(f"Failed to update slot preferences: {e}", exc_info=True)
        return jsonify({'error': 'An internal server error occurred.'}), 500
    finally:
        Session.remove()

# Simple in-process per-user throttle for Cheese slot writes. Each write costs a
# GET + PUT against Cheese Tracker, so we cap how often a user can fire them.
_cheese_write_last = {}
_CHEESE_WRITE_MIN_INTERVAL = timedelta(seconds=2)

# Separate throttle for on-demand tracker refreshes (one CT GET each).
_cheese_refresh_last = {}
_CHEESE_REFRESH_MIN_INTERVAL = timedelta(seconds=3)


@slots_bp.route('/rooms/<int:room_db_id>/cheese/refresh', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def refresh_room_cheese(current_user, room_db_id):
    """
    On-demand refresh of a room's Cheese Tracker cache, bypassing the ~5 minute
    background poll so a user can pull the current state immediately.
    """
    if not current_user.cheese_api_key:
        return jsonify({'error': 'Not connected to Cheese Tracker.'}), 400

    session = Session()
    sub = session.query(UserRoomSubscription).filter_by(
        user_id=current_user.id, room_id=room_db_id
    ).first()
    if not sub:
        return jsonify({'error': 'You are not subscribed to this room.'}), 403

    now = datetime.utcnow()
    last = _cheese_refresh_last.get(current_user.id)
    if last is not None and (now - last) < _CHEESE_REFRESH_MIN_INTERVAL:
        return jsonify({'error': 'Refreshing too fast. Please wait a moment.'}), 429
    _cheese_refresh_last[current_user.id] = now

    from app.api_cheese import refresh_tracker_cache
    app_context = current_app._get_current_object()
    result = refresh_tracker_cache(app_context, current_user.id, room_db_id)

    status = result.get('status')
    if status == 'ok':
        return jsonify({'message': 'Refreshed from Cheese Tracker.'}), 200

    error_map = {
        'not_connected': ('Not connected to Cheese Tracker.', 400),
        'no_tracker': ('This room is not linked to Cheese Tracker.', 400),
        'error': ('Could not reach Cheese Tracker. Please try again.', 502),
    }
    message, code = error_map.get(status, ('Could not refresh.', 500))
    return jsonify({'error': message}), code


@slots_bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/cheese', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_slot_cheese(current_user, room_db_id, slot_id):
    """
    Updates a single slot's Cheese Tracker state (notes / status / ping) and,
    optionally, refreshes its "last checked" timestamp ("Still BK").
    Runs synchronously because the user is waiting on the result.
    """
    if not current_user.cheese_api_key:
        return jsonify({'error': 'Not connected to Cheese Tracker.'}), 400

    data = request.json or {}

    # Build a validated partial-update dict. Only include keys the client sent.
    updates = {}
    if 'notes' in data:
        notes = data['notes']
        if notes is None:
            notes = ''
        if not isinstance(notes, str):
            return jsonify({'error': 'notes must be a string.'}), 400
        if len(notes) > 5000:
            return jsonify({'error': 'notes too long (max 5000 characters).'}), 400
        updates['notes'] = notes
    if 'progression_status' in data:
        val = data['progression_status']
        if val not in VALID_CHEESE_PROGRESSION:
            return jsonify({'error': 'Invalid progression_status.'}), 400
        updates['progression_status'] = val
    if 'completion_status' in data:
        val = data['completion_status']
        if val not in VALID_CHEESE_COMPLETION:
            return jsonify({'error': 'Invalid completion_status.'}), 400
        updates['completion_status'] = val
    if 'discord_ping' in data:
        val = data['discord_ping']
        if val not in VALID_CHEESE_PING:
            return jsonify({'error': 'Invalid discord_ping.'}), 400
        updates['discord_ping'] = val
    if data.get('touch_last_checked'):
        updates['touch_last_checked'] = True

    if not updates:
        return jsonify({'error': 'No valid fields to update.'}), 400

    # Throttle.
    now = datetime.utcnow()
    last = _cheese_write_last.get(current_user.id)
    if last is not None and (now - last) < _CHEESE_WRITE_MIN_INTERVAL:
        return jsonify({'error': 'Too many updates. Please slow down.'}), 429
    _cheese_write_last[current_user.id] = now

    from app.api_cheese import apply_cheese_slot_update
    app_context = current_app._get_current_object()
    result = apply_cheese_slot_update(app_context, current_user.id, room_db_id, slot_id, updates)

    status = result.get('status')
    if status == 'ok':
        my_discord_clean = current_user.discord_username.strip().lower() if current_user.discord_username else None
        cheese_state = build_cheese_slot_state(
            result['game'],
            result.get('global_ping_policy'),
            current_user.cheese_user_id,
            my_discord_clean
        )
        return jsonify({'message': 'Slot updated.', 'cheese': cheese_state}), 200

    error_map = {
        'not_connected': ('Not connected to Cheese Tracker.', 400),
        'no_tracker': ('This room is not linked to Cheese Tracker.', 400),
        'not_tracked': ('You are not tracking this slot.', 403),
        'not_found': ('Slot not found on Cheese Tracker.', 404),
        'forbidden': ('This slot is claimed by someone else on Cheese Tracker.', 403),
        'conflict': ('This slot changed on Cheese Tracker. Please refresh and try again.', 409),
        'error': ('Could not reach Cheese Tracker. Please try again.', 502),
    }
    message, code = error_map.get(status, ('Could not update slot.', 500))
    return jsonify({'error': message}), code


@slots_bp.route('/users/me/tracked-slots', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_user_tracked_slots(current_user):
    session = Session()
    try:
        subscriptions = session.query(UserRoomSubscription).join(TrackedRoom).filter(
            UserRoomSubscription.user_id == current_user.id,
            ~TrackedRoom.room_id.startswith("PENDING_DISCOVERY")
        ).options(
            selectinload(UserRoomSubscription.room),
            selectinload(UserRoomSubscription.tracked_slots)
        ).order_by(UserRoomSubscription.alias).all()

        all_room_uuids = set()
        room_db_to_uuid = {}
        for sub in subscriptions:
            if sub.room and not sub.room.room_id.startswith("PENDING_DISCOVERY"):
                all_room_uuids.add(sub.room.room_id)
                room_db_to_uuid[sub.room_id] = sub.room.room_id

        last_activity_map = {}
        item_count_map = {}
        if all_room_uuids:
            activity_rows = session.query(
                NotifiedItem.room_id,
                NotifiedItem.receiving_slot_id,
                sa_func.max(NotifiedItem.timestamp).label('last_ts'),
                sa_func.count(NotifiedItem.id).label('item_count')
            ).filter(
                NotifiedItem.room_id.in_(all_room_uuids)
            ).group_by(
                NotifiedItem.room_id,
                NotifiedItem.receiving_slot_id
            ).all()
            for row in activity_rows:
                last_activity_map[(row.room_id, row.receiving_slot_id)] = row.last_ts
                item_count_map[(row.room_id, row.receiving_slot_id)] = row.item_count

        response_data = []
        for sub in subscriptions:
            room_data = sub.room
            if not room_data or room_data.room_id.startswith("PENDING_DISCOVERY"):
                continue

            try:
                players_json = json.loads(room_data.cached_players_json or '[]')
                if not isinstance(players_json, list):
                    players_json = []
            except (json.JSONDecodeError, TypeError):
                players_json = []

            players_map = {p['slot_id']: p for p in players_json}
            checks_map = parse_cached_checks(room_data.cached_checks_json)

            # Parse the room's cached Cheese Tracker data (if any) once per room,
            # indexed by slot position, so we can attach per-slot Cheese state.
            # Only build this for users who have connected a Cheese API key.
            cheese_games_map = {}
            cheese_global_ping_policy = None
            room_has_cheese = bool(current_user.cheese_api_key) and bool(room_data.cheese_tracker_id)
            if room_has_cheese and room_data.cached_cheese_json:
                try:
                    cheese_data = json.loads(room_data.cached_cheese_json)
                    if isinstance(cheese_data, dict):
                        cheese_global_ping_policy = cheese_data.get('global_ping_policy')
                        for g in cheese_data.get('games', []):
                            pos = g.get('position')
                            if pos is not None:
                                cheese_games_map[pos] = g
                except (json.JSONDecodeError, TypeError):
                    cheese_games_map = {}

            my_cheese_user_id = current_user.cheese_user_id
            my_discord_clean = current_user.discord_username.strip().lower() if current_user.discord_username else None

            tracked_slots_list = []
            for slot in sorted(sub.tracked_slots, key=lambda s: s.slot_id):
                p_obj = players_map.get(slot.slot_id)
                p_name = p_obj.get('name', f"Player {slot.slot_id}") if p_obj else f"Player {slot.slot_id}"
                p_alias = p_obj.get('alias') if p_obj else None
                p_finished = p_obj.get('is_finished', False) if p_obj else False
                p_all_checks = p_obj.get('has_all_checks', False) if p_obj else False
                p_total_locations = p_obj.get('total_locations', 0) if p_obj else 0
                p_game = p_obj.get('game') if p_obj else None

                slot_last_activity = last_activity_map.get((room_data.room_id, slot.slot_id))
                slot_item_count = item_count_map.get((room_data.room_id, slot.slot_id), 0)

                cheese_state = None
                cheese_game = cheese_games_map.get(slot.slot_id)
                if cheese_game is not None:
                    cheese_state = build_cheese_slot_state(
                        cheese_game,
                        cheese_global_ping_policy,
                        my_cheese_user_id,
                        my_discord_clean
                    )

                tracked_slots_list.append({
                    'slot_id': slot.slot_id,
                    'player_name': p_name,
                    'player_alias': p_alias,
                    # Goal-only, for backward compatibility with older app builds.
                    'is_finished': p_finished,
                    'has_all_checks': p_all_checks,
                    'checks_done': checks_map.get(slot.slot_id, 0),
                    'total_locations': p_total_locations,
                    'game': p_game,
                    'last_activity': format_iso_z(slot_last_activity),
                    'item_count': slot_item_count,
                    'needs_backfill': slot.needs_backfill,
                    'notify_progression': slot.notify_progression,
                    'notify_useful': slot.notify_useful,
                    'notify_filler': slot.notify_filler,
                    'notify_trap': slot.notify_trap,
                    'notify_hints': slot.notify_hints,
                    'notify_hints_remote_items': slot.notify_hints_remote_items,
                    'notify_finished': slot.notify_finished,
                    'finished_definition': slot.finished_definition,
                    'use_condensed_messages': slot.use_condensed_messages,
                    'combine_notifications': slot.combine_notifications,
                    'suppress_own_events': slot.suppress_own_events,
                    'remove_emojis': slot.remove_emojis,
                    'suppress_self_found': slot.suppress_self_found,
                    'suppress_connected': slot.suppress_connected,
                    'snooze_until': format_iso_z(slot.snooze_until),
                    'cheese': cheese_state
                })

            response_data.append({
                'room_db_id': sub.room_id,
                'room_id': room_data.room_id,
                'room_alias': sub.alias,
                'icon_name': sub.icon_name,
                'is_archived': sub.is_archived,
                'host': room_data.cached_full_address,
                'players': players_json,
                'tracked_slots': tracked_slots_list
            })

        return jsonify(response_data)
    finally:
        Session.remove()

@slots_bp.route('/users/me/ignore-list', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_ignore_list(current_user):
    session = Session()
    try:
        ignore_items = session.query(UserIgnoreItem).filter_by(user_id=current_user.id).all()
        items = []
        for item in ignore_items:
            items.append({
                'id': item.id,
                'item_name': item.item_name,
                'game_name': item.game_name,
                'is_group': getattr(item, 'is_group', False),
                'created_at': item.created_at.isoformat()
            })
        return jsonify(items)
    finally:
        Session.remove()

@slots_bp.route('/users/me/ignore-list', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def add_ignore_item(current_user):
    data = request.json or {}
    item_name = data.get('item_name', '').strip()
    game_name = data.get('game_name')
    raw_is_group = data.get('is_group', False)

    if isinstance(raw_is_group, bool):
        is_group = raw_is_group
    elif isinstance(raw_is_group, str):
        val_lower = raw_is_group.strip().lower()
        if val_lower in ("true", "1"):
            is_group = True
        elif val_lower in ("false", "0"):
            is_group = False
        else:
            return jsonify({'error': 'is_group must be a boolean or a valid string representation'}), 400
    elif raw_is_group is None:
        is_group = False
    else:
        return jsonify({'error': 'is_group must be a boolean or a valid string representation'}), 400
    
    if game_name:
        game_name = game_name.strip()

    if is_group and not game_name:
        return jsonify({'error': 'game_name is required for group ignore rules'}), 400

    if not item_name:
        return jsonify({'error': 'item_name is required'}), 400

    session = Session()
    try:
        existing = session.query(UserIgnoreItem).filter_by(
            user_id=current_user.id,
            item_name=item_name,
            game_name=game_name
        ).first()

        if existing:
            return jsonify({'error': 'This item is already in your ignore list.'}), 409

        new_item = UserIgnoreItem(
            user_id=current_user.id,
            item_name=item_name,
            game_name=game_name,
            is_group=is_group
        )
        session.add(new_item)
        session.commit()
        
        logging.info(f"[API] User {current_user.id} ignored '{item_name}' (Game: {game_name or 'Global'}, Group: {is_group})")
        return jsonify({
            'message': 'Item added to ignore list.',
            'id': new_item.id
        }), 201
    except Exception as e:
        session.rollback()
        raise e
    finally:
        Session.remove()

@slots_bp.route('/users/me/ignore-list/<int:item_id>', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_ignore_item(current_user, item_id):
    data = request.json or {}
    new_item_name = data.get('item_name', '').strip()
    raw_is_group = data.get('is_group', False)

    if isinstance(raw_is_group, bool):
        new_is_group = raw_is_group
    elif isinstance(raw_is_group, str):
        val_lower = raw_is_group.strip().lower()
        if val_lower in ("true", "1"):
            new_is_group = True
        elif val_lower in ("false", "0"):
            new_is_group = False
        else:
            return jsonify({'error': 'is_group must be a boolean or a valid string representation'}), 400
    elif raw_is_group is None:
        new_is_group = False
    else:
        return jsonify({'error': 'is_group must be a boolean or a valid string representation'}), 400
    
    new_game_name = data.get('game_name')
    if new_game_name:
        new_game_name = new_game_name.strip()

    if new_is_group and not new_game_name:
        return jsonify({'error': 'game_name is required for group ignore rules'}), 400

    if not new_item_name:
        return jsonify({'error': 'item_name is required'}), 400

    session = Session()
    try:
        item = session.query(UserIgnoreItem).filter_by(id=item_id, user_id=current_user.id).first()
        if not item:
            return jsonify({'error': 'Rule not found'}), 404

        existing = session.query(UserIgnoreItem).filter(
            UserIgnoreItem.user_id == current_user.id,
            UserIgnoreItem.item_name == new_item_name,
            UserIgnoreItem.game_name == new_game_name,
            UserIgnoreItem.id != item_id 
        ).first()

        if existing:
            return jsonify({'error': 'A rule for this item/game already exists.'}), 409

        item.item_name = new_item_name
        item.game_name = new_game_name
        item.is_group = new_is_group
        
        session.commit()
        return jsonify({'message': 'Rule updated.'})
    finally:
        Session.remove()

@slots_bp.route('/users/me/ignore-list/<int:item_id>', methods=['DELETE'])
@handle_db_errors
@log_api_call
@token_required
def remove_ignore_item(current_user, item_id):
    session = Session()
    try:
        item = session.query(UserIgnoreItem).filter_by(
            id=item_id, 
            user_id=current_user.id
        ).first()

        if not item:
            return jsonify({'error': 'Item not found'}), 404

        session.delete(item)
        session.commit()
        logging.info(f"[API] User {current_user.id} removed ignore rule {item_id}")
        return jsonify({'message': 'Item removed from ignore list.'})
    except Exception as e:
        session.rollback()
        raise e
    finally:
        Session.remove()

@slots_bp.route('/users/me/whitelist', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_whitelist(current_user):
    session = Session()
    try:
        whitelist_items = session.query(UserWhitelistItem).filter_by(user_id=current_user.id).all()
        items = []
        for item in whitelist_items:
            items.append({
                'id': item.id,
                'item_name': item.item_name,
                'game_name': item.game_name,
                'is_group': getattr(item, 'is_group', False),
                'created_at': item.created_at.isoformat()
            })
        return jsonify(items)
    finally:
        Session.remove()

@slots_bp.route('/users/me/whitelist', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def add_whitelist_item(current_user):
    data = request.json or {}
    item_name = data.get('item_name', '').strip()
    game_name = data.get('game_name')
    raw_is_group = data.get('is_group', False)

    if isinstance(raw_is_group, bool):
        is_group = raw_is_group
    elif isinstance(raw_is_group, str):
        val_lower = raw_is_group.strip().lower()
        if val_lower in ("true", "1"):
            is_group = True
        elif val_lower in ("false", "0"):
            is_group = False
        else:
            return jsonify({'error': 'is_group must be a boolean or a valid string representation'}), 400
    elif raw_is_group is None:
        is_group = False
    else:
        return jsonify({'error': 'is_group must be a boolean or a valid string representation'}), 400
    
    if game_name:
        game_name = game_name.strip()

    if is_group and not game_name:
        return jsonify({'error': 'game_name is required for group whitelist rules'}), 400

    if not item_name:
        return jsonify({'error': 'item_name is required'}), 400

    session = Session()
    try:
        existing = session.query(UserWhitelistItem).filter_by(
            user_id=current_user.id,
            item_name=item_name,
            game_name=game_name
        ).first()

        if existing:
            return jsonify({'error': 'This item is already in your whitelist.'}), 409

        new_item = UserWhitelistItem(
            user_id=current_user.id,
            item_name=item_name,
            game_name=game_name,
            is_group=is_group
        )
        session.add(new_item)
        session.commit()
        
        logging.info(f"[API] User {current_user.id} whitelisted '{item_name}' (Game: {game_name or 'Global'}, Group: {is_group})")
        return jsonify({
            'message': 'Item added to whitelist.',
            'id': new_item.id
        }), 201
    except Exception as e:
        session.rollback()
        raise e
    finally:
        Session.remove()

@slots_bp.route('/users/me/whitelist/<int:item_id>', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_whitelist_item(current_user, item_id):
    data = request.json or {}
    new_item_name = data.get('item_name', '').strip()
    raw_is_group = data.get('is_group', False)

    if isinstance(raw_is_group, bool):
        new_is_group = raw_is_group
    elif isinstance(raw_is_group, str):
        val_lower = raw_is_group.strip().lower()
        if val_lower in ("true", "1"):
            new_is_group = True
        elif val_lower in ("false", "0"):
            new_is_group = False
        else:
            return jsonify({'error': 'is_group must be a boolean or a valid string representation'}), 400
    elif raw_is_group is None:
        new_is_group = False
    else:
        return jsonify({'error': 'is_group must be a boolean or a valid string representation'}), 400
    
    new_game_name = data.get('game_name')
    if new_game_name:
        new_game_name = new_game_name.strip()

    if new_is_group and not new_game_name:
        return jsonify({'error': 'game_name is required for group whitelist rules'}), 400

    if not new_item_name:
        return jsonify({'error': 'item_name is required'}), 400

    session = Session()
    try:
        item = session.query(UserWhitelistItem).filter_by(id=item_id, user_id=current_user.id).first()
        if not item:
            return jsonify({'error': 'Rule not found'}), 404

        existing = session.query(UserWhitelistItem).filter(
            UserWhitelistItem.user_id == current_user.id,
            UserWhitelistItem.item_name == new_item_name,
            UserWhitelistItem.game_name == new_game_name,
            UserWhitelistItem.id != item_id 
        ).first()

        if existing:
            return jsonify({'error': 'A rule for this item/game already exists.'}), 409

        item.item_name = new_item_name
        item.game_name = new_game_name
        item.is_group = new_is_group
        
        session.commit()
        return jsonify({'message': 'Rule updated.'})
    finally:
        Session.remove()

@slots_bp.route('/users/me/whitelist/<int:item_id>', methods=['DELETE'])
@handle_db_errors
@log_api_call
@token_required
def remove_whitelist_item(current_user, item_id):
    session = Session()
    try:
        item = session.query(UserWhitelistItem).filter_by(
            id=item_id, 
            user_id=current_user.id
        ).first()

        if not item:
            return jsonify({'error': 'Item not found'}), 404

        session.delete(item)
        session.commit()
        logging.info(f"[API] User {current_user.id} removed whitelist rule {item_id}")
        return jsonify({'message': 'Item removed from whitelist.'})
    except Exception as e:
        session.rollback()
        raise e
    finally:
        Session.remove()

@slots_bp.route('/users/me/snooze', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def set_global_snooze(current_user):
    data = request.json or {}
    duration = data.get('duration_minutes')

    if duration is None or not isinstance(duration, int):
        return jsonify({'error': 'duration_minutes (int) is required'}), 400

    session = Session()
    user = session.query(User).filter_by(id=current_user.id).first()
    
    if duration <= 0:
        user.global_snooze_until = None
        logging.info(f"[API] User {user.id} disabled global snooze.")
        message = "Global snooze disabled."
    else:
        snooze_until = datetime.utcnow() + timedelta(minutes=duration)
        user.global_snooze_until = snooze_until
        logging.info(f"[API] User {user.id} snoozed all notifications for {duration} mins.")
        message = f"App snoozed for {duration} minutes."

    session.commit()
    return jsonify({
        'message': message,
        'snooze_until': format_iso_z(user.global_snooze_until)
    })

@slots_bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/snooze', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def set_slot_snooze(current_user, room_db_id, slot_id):
    data = request.json or {}
    duration = data.get('duration_minutes')

    if duration is None or not isinstance(duration, int):
        return jsonify({'error': 'duration_minutes (int) is required'}), 400

    session = Session()
    slot = session.query(UserTrackedSlot).filter_by(
        user_id=current_user.id,
        room_id=room_db_id,
        slot_id=slot_id
    ).first()

    if not slot:
        return jsonify({'error': 'Tracked slot not found'}), 404

    if duration <= 0:
        slot.snooze_until = None
        logging.info(f"[API] User {current_user.id} unsnoozed slot {slot_id} in room {room_db_id}.")
        message = "Slot snooze disabled."
    else:
        snooze_until = datetime.utcnow() + timedelta(minutes=duration)
        slot.snooze_until = snooze_until
        logging.info(f"[API] User {current_user.id} snoozed slot {slot_id} for {duration} mins.")
        message = f"Player snoozed for {duration} minutes."

    session.commit()
    return jsonify({
        'message': message,
        'snooze_until': format_iso_z(slot.snooze_until)
    })
