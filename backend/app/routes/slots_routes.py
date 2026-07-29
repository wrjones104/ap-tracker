import logging
import json
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.orm import selectinload
from sqlalchemy import func as sa_func

from app import Session
from app.models import (
    User, TrackedRoom, UserRoomSubscription, UserTrackedSlot,
    UserIgnoreItem, NotifiedItem
)
from app.routes.common import log_api_call, token_required, handle_db_errors, format_iso_z

slots_bp = Blueprint('slots_routes', __name__)

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

        session.commit()
        return jsonify({'message': 'Slot preferences updated successfully'}), 200
    except Exception as e:
        session.rollback()
        logging.error(f"Failed to update slot preferences: {e}", exc_info=True)
        return jsonify({'error': 'An internal server error occurred.'}), 500
    finally:
        Session.remove()

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
        if all_room_uuids:
            activity_rows = session.query(
                NotifiedItem.room_id,
                NotifiedItem.receiving_slot_id,
                sa_func.max(NotifiedItem.timestamp).label('last_ts')
            ).filter(
                NotifiedItem.room_id.in_(all_room_uuids)
            ).group_by(
                NotifiedItem.room_id,
                NotifiedItem.receiving_slot_id
            ).all()
            for row in activity_rows:
                last_activity_map[(row.room_id, row.receiving_slot_id)] = row.last_ts

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

            tracked_slots_list = []
            for slot in sorted(sub.tracked_slots, key=lambda s: s.slot_id):
                p_obj = players_map.get(slot.slot_id)
                p_name = p_obj.get('name', f"Player {slot.slot_id}") if p_obj else f"Player {slot.slot_id}"
                p_alias = p_obj.get('alias') if p_obj else None
                p_finished = p_obj.get('is_finished', False) if p_obj else False
                p_game = p_obj.get('game') if p_obj else None

                slot_last_activity = last_activity_map.get((room_data.room_id, slot.slot_id))

                tracked_slots_list.append({
                    'slot_id': slot.slot_id,
                    'player_name': p_name,
                    'player_alias': p_alias,
                    'is_finished': p_finished,
                    'game': p_game,
                    'last_activity': format_iso_z(slot_last_activity),
                    'needs_backfill': slot.needs_backfill,
                    'notify_progression': slot.notify_progression,
                    'notify_useful': slot.notify_useful,
                    'notify_filler': slot.notify_filler,
                    'notify_trap': slot.notify_trap,
                    'notify_hints': slot.notify_hints,
                    'notify_hints_remote_items': slot.notify_hints_remote_items,
                    'notify_finished': slot.notify_finished,
                    'use_condensed_messages': slot.use_condensed_messages,
                    'combine_notifications': slot.combine_notifications,
                    'suppress_own_events': slot.suppress_own_events,
                    'remove_emojis': slot.remove_emojis,
                    'suppress_self_found': slot.suppress_self_found,
                    'suppress_connected': slot.suppress_connected,
                    'snooze_until': format_iso_z(slot.snooze_until)
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
