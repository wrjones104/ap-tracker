import logging
from flask import Blueprint, request, jsonify
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from app import Session
from app.models import MilestoneTemplate, MilestoneTemplateItem
from app.routes.common import log_api_call, token_required, handle_db_errors

templates_bp = Blueprint('templates_routes', __name__)


def _serialize_template(t):
    return {
        'id': t.id,
        'name': t.name,
        'game_name': t.game_name,
        'auto_apply': bool(t.auto_apply),
        'items': [
            {
                'id': item.id,
                'item_name': item.item_name,
                'quantity': item.quantity,
                'is_group': item.is_group,
            }
            for item in t.items
        ]
    }


def _validate_items(items_data):
    """Returns a list of valid (item_name, quantity, is_group) tuples or empty list."""
    if not isinstance(items_data, list):
        return []
    valid = []
    for item_data in items_data:
        if not isinstance(item_data, dict):
            continue
        item_name = (item_data.get('item_name') or '').strip()
        quantity = item_data.get('quantity', 1)
        is_group = bool(item_data.get('is_group', False))
        if item_name and isinstance(quantity, int) and not isinstance(quantity, bool) and quantity >= 1:
            valid.append((item_name, quantity, is_group))
    return valid


@templates_bp.route('/milestone-templates', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def get_milestone_templates(current_user):
    game = request.args.get('game')
    session = Session()
    try:
        query = session.query(MilestoneTemplate).filter_by(
            user_id=current_user.id
        ).options(selectinload(MilestoneTemplate.items))

        if game:
            query = query.filter(
                func.lower(MilestoneTemplate.game_name) == game.lower()
            )

        templates = query.order_by(MilestoneTemplate.game_name, MilestoneTemplate.name).all()
        return jsonify([_serialize_template(t) for t in templates])
    finally:
        Session.remove()


@templates_bp.route('/milestone-templates', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def create_milestone_template(current_user):
    data = request.json or {}
    name = (data.get('name') or '').strip()
    game_name = (data.get('game_name') or '').strip()
    items_data = data.get('items', [])

    if not name:
        return jsonify({'error': 'Template name is required'}), 400
    if not game_name:
        return jsonify({'error': 'Game name is required'}), 400

    valid_items = _validate_items(items_data)
    if not valid_items:
        return jsonify({'error': 'At least one valid item is required'}), 400

    session = Session()
    try:
        template = MilestoneTemplate(
            user_id=current_user.id,
            game_name=game_name,
            name=name,
            auto_apply=bool(data.get('auto_apply', False)),
        )
        session.add(template)
        session.flush()

        for item_name, quantity, is_group in valid_items:
            session.add(MilestoneTemplateItem(
                template_id=template.id,
                item_name=item_name,
                quantity=quantity,
                is_group=is_group,
            ))

        session.commit()
        return jsonify({'message': 'Template created', 'id': template.id}), 201

    except IntegrityError:
        session.rollback()
        return jsonify({'error': 'A template with that name already exists for this game'}), 409
    except Exception as e:
        session.rollback()
        logging.error(f"Failed to create milestone template: {e}", exc_info=True)
        return jsonify({'error': 'Failed to create template'}), 500
    finally:
        Session.remove()


@templates_bp.route('/milestone-templates/<int:template_id>', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def update_milestone_template(current_user, template_id):
    data = request.json or {}
    name = (data.get('name') or '').strip()
    game_name = (data.get('game_name') or '').strip()
    items_data = data.get('items', [])

    if not name:
        return jsonify({'error': 'Template name is required'}), 400
    if not game_name:
        return jsonify({'error': 'Game name is required'}), 400

    valid_items = _validate_items(items_data)
    if not valid_items:
        return jsonify({'error': 'At least one valid item is required'}), 400

    session = Session()
    try:
        template = session.query(MilestoneTemplate).filter_by(
            id=template_id,
            user_id=current_user.id,
        ).options(selectinload(MilestoneTemplate.items)).first()

        if not template:
            return jsonify({'error': 'Template not found'}), 404

        template.name = name
        template.game_name = game_name
        if 'auto_apply' in data:
            template.auto_apply = bool(data.get('auto_apply'))
        template.items.clear()

        for item_name, quantity, is_group in valid_items:
            template.items.append(MilestoneTemplateItem(
                template_id=template.id,
                item_name=item_name,
                quantity=quantity,
                is_group=is_group,
            ))

        session.commit()
        return jsonify({'message': 'Template updated', 'id': template.id})

    except IntegrityError:
        session.rollback()
        return jsonify({'error': 'A template with that name already exists for this game'}), 409
    except Exception as e:
        session.rollback()
        logging.error(f"Failed to update milestone template {template_id}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to update template'}), 500
    finally:
        Session.remove()


@templates_bp.route('/milestone-templates/<int:template_id>/auto-apply', methods=['PUT'])
@handle_db_errors
@log_api_call
@token_required
def set_milestone_template_auto_apply(current_user, template_id):
    """
    Flips one template's "always add to new slots I play for this game" switch.

    Separate from the full update so the switch in the app does not have to round-trip every
    item just to change a boolean -- and so a stale client cannot silently revert a template's
    items while toggling it.
    """
    data = request.json or {}
    if 'auto_apply' not in data:
        return jsonify({'error': 'auto_apply is required'}), 400

    session = Session()
    try:
        template = session.query(MilestoneTemplate).filter_by(
            id=template_id,
            user_id=current_user.id,
        ).first()

        if not template:
            return jsonify({'error': 'Template not found'}), 404

        template.auto_apply = bool(data.get('auto_apply'))
        session.commit()
        return jsonify({'message': 'Template updated', 'auto_apply': template.auto_apply})
    finally:
        Session.remove()


@templates_bp.route('/milestone-templates/<int:template_id>', methods=['DELETE'])
@handle_db_errors
@log_api_call
@token_required
def delete_milestone_template(current_user, template_id):
    session = Session()
    try:
        template = session.query(MilestoneTemplate).filter_by(
            id=template_id,
            user_id=current_user.id,
        ).first()

        if not template:
            return jsonify({'error': 'Template not found'}), 404

        session.delete(template)
        session.commit()
        return jsonify({'message': 'Template deleted'})
    finally:
        Session.remove()
