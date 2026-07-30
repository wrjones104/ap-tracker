import logging
import json
from app.models import DatapackageCache, SlotItemCount
from app.utils import is_snoozed

def evaluate_threshold_groups(session, room_db_id, room_uuid, game_checksums, groups_by_slot, new_items_for_notify, users_by_id, prefs_by_user_slot, tracked_slots_by_user, aliases_by_user, full_name_map, short_name_map, backfill_check_set, now_utc):
    """
    Evaluates milestone threshold groups (AND-logic condition check) when slots receive new items.
    """
    notifications_by_user = {}
    
    if not groups_by_slot or not new_items_for_notify:
        return notifications_by_user
    
    evaluation_targets = {}
    for item_data in new_items_for_notify:
        rid = item_data['receiving_slot_id']
        game_checksum = item_data.get('game_checksum')
        
        for user_id, tracked_slots in tracked_slots_by_user.items():
            if rid in tracked_slots:
                sp = prefs_by_user_slot.get(user_id, {}).get(rid)
                if sp and sp.id in groups_by_slot:
                    if sp.id not in evaluation_targets:
                        evaluation_targets[sp.id] = {
                            'slot_id': rid,
                            'game_checksum': game_checksum,
                            'user_id': user_id
                        }
    
    if not evaluation_targets:
        return notifications_by_user
    
    all_checksums = set(info['game_checksum'] for info in evaluation_targets.values() if info['game_checksum'])
    
    name_to_id_by_checksum = {}
    group_expansion_by_checksum = {}
    
    if all_checksums:
        try:
            name_results = session.query(
                DatapackageCache.checksum, DatapackageCache.entity_name, DatapackageCache.entity_id
            ).filter(
                DatapackageCache.checksum.in_(all_checksums),
                DatapackageCache.entity_type == 'item'
            ).all()
            for chk, name, eid in name_results:
                name_to_id_by_checksum.setdefault(chk, {})[name.lower().strip()] = eid
            
            member_results = session.query(
                DatapackageCache.checksum, DatapackageCache.entity_name
            ).filter(
                DatapackageCache.checksum.in_(all_checksums),
                DatapackageCache.entity_type == 'item_name_groups_json'
            ).all()
            for chk, name_groups_str in member_results:
                try:
                    parsed_data = json.loads(name_groups_str)
                    if isinstance(parsed_data, dict):
                        for g_name, items in parsed_data.items():
                            if isinstance(items, list):
                                group_expansion_by_checksum.setdefault(chk, {}).setdefault(
                                    g_name.lower().strip(), set()
                                ).update(item.lower().strip() for item in items)
                except Exception:
                    pass
        except Exception as e:
            logging.error(f"[THRESHOLD_GROUP_ERROR] Failed to fetch name/group mappings: {e}", exc_info=True)
            return notifications_by_user
    
    counts_by_slot = {info['slot_id']: {} for info in evaluation_targets.values()}
    slot_ids = list(counts_by_slot.keys())
    if slot_ids:
        try:
            counts = session.query(SlotItemCount).filter(
                SlotItemCount.room_id == room_uuid,
                SlotItemCount.slot_id.in_(slot_ids)
            ).all()
            for c in counts:
                counts_by_slot[c.slot_id][c.item_id] = c.count
        except Exception as e:
            logging.error(f"[THRESHOLD_GROUP_ERROR] Failed to batch fetch counts: {e}")
    
    for db_slot_id, info in evaluation_targets.items():
        slot_id = info['slot_id']
        user_id = info['user_id']
        game_checksum = info['game_checksum']
        
        if not game_checksum:
            continue
        
        if (user_id, slot_id) in backfill_check_set:
            continue
        
        user_prefs = users_by_id.get(user_id)
        slot_prefs = prefs_by_user_slot.get(user_id, {}).get(slot_id)
        if not user_prefs or not slot_prefs:
            continue
        if is_snoozed(user_prefs, slot_prefs, now_utc, user_id, slot_id, "milestone"):
            continue
        
        name_to_id = name_to_id_by_checksum.get(game_checksum, {})
        group_expansions = group_expansion_by_checksum.get(game_checksum, {})
        item_counts_for_slot = counts_by_slot.get(slot_id, {})
        
        groups = groups_by_slot.get(db_slot_id, [])
        
        for group in groups:
            if group.is_triggered:
                continue
            
            all_met = True
            for item_req in group.items:
                if item_req.is_group:
                    members = group_expansions.get(item_req.item_name.lower().strip(), set())
                    total = 0
                    for member_name in members:
                        member_id = name_to_id.get(member_name)
                        if member_id is not None:
                            total += item_counts_for_slot.get(member_id, 0)
                    if total < item_req.quantity:
                        all_met = False
                        break
                else:
                    item_id = name_to_id.get(item_req.item_name.lower().strip())
                    if item_id is None:
                        all_met = False
                        break
                    if item_counts_for_slot.get(item_id, 0) < item_req.quantity:
                        all_met = False
                        break
            
            if all_met:
                group.is_triggered = True
                logging.info(f"[THRESHOLD_GROUP_HIT] User {user_id}: Slot {slot_id} group '{group.name or 'unnamed'}' (ID={group.id}) triggered!")
                
                remove_emojis = user_prefs.remove_emojis_default
                if slot_prefs and slot_prefs.remove_emojis is not None:
                    remove_emojis = slot_prefs.remove_emojis
                
                icon_milestone = "" if remove_emojis else "🚩 "
                room_alias = aliases_by_user.get(user_id, "Unknown Room")
                
                if group.name:
                    title = f"{icon_milestone}{group.name} - [{room_alias}]"
                else:
                    first_item = group.items[0].item_name if group.items else "Unknown"
                    if len(group.items) > 1:
                        title = f"{icon_milestone}Milestone Reached! {first_item} + {len(group.items) - 1} others - [{room_alias}]"
                    else:
                        title = f"{icon_milestone}Milestone Reached! {first_item} - [{room_alias}]"
                
                item_parts = []
                for item_req in group.items:
                    suffix = " (Group)" if item_req.is_group else ""
                    item_parts.append(f"{item_req.quantity}× {item_req.item_name}{suffix}")
                
                player_name = full_name_map.get(slot_id, f"Slot {slot_id}")
                body = f"{player_name}: {', '.join(item_parts)}"
                
                notifications_by_user.setdefault(user_id, []).append({
                    'title': title,
                    'body': body,
                    'type': 'item_milestone',
                    'details': (room_db_id, user_id, group.id)
                })

    return notifications_by_user
