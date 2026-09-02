import logging
from flask import Blueprint, request, jsonify
from sqlalchemy.orm import selectinload

from app import Session
from app.models import UserTrackedSlot, ThresholdGroup, ThresholdGroupItem, TrackedRoom
from app.routes.common import log_api_call, token_required, handle_db_errors
from app.services.threshold_service import compute_requirement_progress
from app.services.milestone_template_service import (
    MAX_GROUPS_PER_SLOT,
    count_groups,
    create_group,
    existing_group_names,
)

thresholds_bp = Blueprint('thresholds_routes', __name__)

@thresholds_bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/threshold-groups', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_threshold_groups(current_user, room_db_id, slot_id):
    session = Session()
    try:
        tracked_slot = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id,
            room_id=room_db_id,
            slot_id=slot_id
        ).first()
        if not tracked_slot:
            return jsonify({'error': 'Tracked slot not found'}), 404
        
        groups = session.query(ThresholdGroup).filter_by(
            user_tracked_slot_id=tracked_slot.id
        ).options(selectinload(ThresholdGroup.items)).all()

        # Progress is advisory: clients render it, they do not act on it, and item-group
        # requirements are the only ones they cannot count for themselves. Never let a failure
        # here take down the definitions fetch -- 'acquired' simply comes back null.
        progress = {}
        all_items = [item for g in groups for item in g.items]
        if all_items:
            try:
                room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
                if room:
                    progress = compute_requirement_progress(session, room, slot_id, all_items)
            except Exception as e:
                logging.error(
                    f"Failed to compute milestone progress for room {room_db_id} slot {slot_id}: {e}",
                    exc_info=True
                )

        return jsonify([{
            'id': g.id,
            'name': g.name,
            'is_triggered': g.is_triggered,
            'items': [{
                'id': item.id,
                'item_name': item.item_name,
                'quantity': item.quantity,
                'is_group': item.is_group,
                'acquired': progress.get(item.id)
            } for item in g.items]
        } for g in groups])
    finally:
        Session.remove()

@thresholds_bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/threshold-groups', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def create_threshold_group(current_user, room_db_id, slot_id):
    data = request.json or {}
    items_data = data.get('items', [])
    
    if not items_data:
        return jsonify({'error': 'At least one item is required'}), 400
        
    session = Session()
    try:
        tracked_slot = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id,
            room_id=room_db_id,
            slot_id=slot_id
        ).first()
        if not tracked_slot:
            return jsonify({'error': 'Tracked slot not found'}), 404
            
        group = ThresholdGroup(
            user_tracked_slot_id=tracked_slot.id,
            name=(data.get('name') or '').strip() or None,
            is_triggered=False
        )
        session.add(group)
        session.flush()
        
        valid_items_count = 0
        for item_data in items_data:
            item_name = item_data.get('item_name', '').strip()
            quantity = item_data.get('quantity', 1)
            is_group = item_data.get('is_group', False)
            
            if not item_name or quantity < 1:
                continue
                
            group_item = ThresholdGroupItem(
                group_id=group.id,
                item_name=item_name,
                quantity=quantity,
                is_group=is_group
            )
            session.add(group_item)
            valid_items_count += 1
            
        if valid_items_count == 0:
            session.rollback()
            return jsonify({'error': 'No valid items provided'}), 400
            
        session.commit()
        return jsonify({
            'message': 'Threshold group created',
            'id': group.id
        }), 201
    except Exception as e:
        session.rollback()
        logging.error(f"Failed to create threshold group: {e}", exc_info=True)
        return jsonify({'error': 'Failed to create threshold group'}), 500
    finally:
        Session.remove()


@thresholds_bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/threshold-groups/bulk', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def create_threshold_groups_bulk(current_user, room_db_id, slot_id):
    """
    Creates several milestone groups on one slot in a single transaction.

    Behind the app's "Apply Templates" sheet, where ticking three templates has to mean three
    groups or none -- looping the single-create endpoint would leave a half-applied slot on the
    first failure, and cost a round trip, a group refetch and a widget refresh per template.

    Groups whose items are all absent from this seed, or whose name duplicates a group already
    on the slot, are reported in 'skipped' rather than failing the request: the client cannot
    always know which templates still resolve, and a partial apply the user is told about is
    more useful than a rejection.
    """
    data = request.json or {}
    groups_data = data.get('groups', [])

    if not isinstance(groups_data, list) or not groups_data:
        return jsonify({'error': 'At least one group is required'}), 400
    if len(groups_data) > MAX_GROUPS_PER_SLOT:
        return jsonify({'error': f'At most {MAX_GROUPS_PER_SLOT} groups can be applied at once'}), 400

    session = Session()
    try:
        tracked_slot = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id,
            room_id=room_db_id,
            slot_id=slot_id
        ).first()
        if not tracked_slot:
            return jsonify({'error': 'Tracked slot not found'}), 404

        taken = existing_group_names(session, tracked_slot.id)
        already = count_groups(session, tracked_slot.id)
        if already + len(groups_data) > MAX_GROUPS_PER_SLOT:
            return jsonify({
                'error': f'A slot can hold at most {MAX_GROUPS_PER_SLOT} milestone groups'
            }), 400

        created = []
        skipped = []
        for entry in groups_data:
            if not isinstance(entry, dict):
                continue
            name = (entry.get('name') or '').strip()
            raw_items = entry.get('items', [])
            if not isinstance(raw_items, list):
                raw_items = []

            valid_items = []
            for item_data in raw_items:
                if not isinstance(item_data, dict):
                    continue
                item_name = (item_data.get('item_name') or '').strip()
                quantity = item_data.get('quantity', 1)
                if not isinstance(quantity, int) or isinstance(quantity, bool):
                    continue
                if item_name and quantity >= 1:
                    valid_items.append((item_name, quantity, bool(item_data.get('is_group', False))))

            if not valid_items:
                skipped.append({'name': name or None, 'reason': 'no_valid_items'})
                continue
            if name and name.lower() in taken:
                skipped.append({'name': name, 'reason': 'duplicate_name'})
                continue

            group = create_group(session, tracked_slot.id, name, valid_items)
            if name:
                taken.add(name.lower())
            created.append(group)

        if not created:
            session.rollback()
            return jsonify({
                'error': 'No groups could be created',
                'skipped': skipped
            }), 400

        session.commit()
        return jsonify({
            'message': f'Created {len(created)} milestone group(s)',
            'created': [{'id': g.id, 'name': g.name} for g in created],
            'skipped': skipped
        }), 201
    except Exception as e:
        session.rollback()
        logging.error(
            f"Failed to bulk-create threshold groups for room {room_db_id} slot {slot_id}: {e}",
            exc_info=True
        )
        return jsonify({'error': 'Failed to create milestone groups'}), 500
    finally:
        Session.remove()


@thresholds_bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/threshold-groups/<int:group_id>', methods=['DELETE'])
@handle_db_errors
@log_api_call
@token_required
def delete_threshold_group(current_user, room_db_id, slot_id, group_id):
    session = Session()
    try:
        tracked_slot = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id,
            room_id=room_db_id,
            slot_id=slot_id
        ).first()
        if not tracked_slot:
            return jsonify({'error': 'Tracked slot not found'}), 404
            
        group = session.query(ThresholdGroup).filter_by(
            id=group_id,
            user_tracked_slot_id=tracked_slot.id
        ).first()
        
        if not group:
            return jsonify({'error': 'Threshold group not found'}), 404
            
        session.delete(group)
        session.commit()
        return jsonify({'message': 'Threshold group deleted'})
    finally:
        Session.remove()

@thresholds_bp.route('/rooms/<int:room_db_id>/slots/<int:slot_id>/threshold-groups/<int:group_id>', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_threshold_group(current_user, room_db_id, slot_id, group_id):
    data = request.json or {}
    items_data = data.get('items', [])
    
    if not items_data:
        return jsonify({'error': 'At least one item is required'}), 400
        
    valid_items = []
    for item_data in items_data:
        item_name = item_data.get('item_name', '').strip()
        quantity = item_data.get('quantity', 1)
        is_group = item_data.get('is_group', False)
        
        if item_name and quantity >= 1:
            valid_items.append((item_name, quantity, is_group))
            
    if not valid_items:
        return jsonify({'error': 'No valid items provided'}), 400
        
    session = Session()
    try:
        tracked_slot = session.query(UserTrackedSlot).filter_by(
            user_id=current_user.id,
            room_id=room_db_id,
            slot_id=slot_id
        ).first()
        if not tracked_slot:
            return jsonify({'error': 'Tracked slot not found'}), 404

        group = session.query(ThresholdGroup).filter_by(
            id=group_id,
            user_tracked_slot_id=tracked_slot.id
        ).first()

        if not group:
            return jsonify({'error': 'Threshold group not found'}), 404

        if group.is_triggered:
            return jsonify({'error': 'Cannot edit a satisfied milestone group'}), 400

        group.name = (data.get('name') or '').strip() or None
        # Flush the delete-orphan cascade before re-inserting, so an item the user removed and
        # re-added in the same edit does not collide with its own outgoing row.
        group.items.clear()
        session.flush()
        for item_name, quantity, is_group in valid_items:
            group.items.append(ThresholdGroupItem(
                item_name=item_name,
                quantity=quantity,
                is_group=is_group
            ))

        session.commit()
        return jsonify({
            'message': 'Threshold group updated',
            'id': group.id
        }), 200
    except Exception as e:
        session.rollback()
        logging.error(f"Failed to update threshold group: {e}", exc_info=True)
        return jsonify({'error': 'Failed to update threshold group'}), 500
    finally:
        Session.remove()
