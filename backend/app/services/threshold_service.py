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


def reconcile_slot_item_counts(session=None):
    """
    Recalculates SlotItemCount table directly from NotifiedItem table room by room.
    Also audits triggered ThresholdGroups for each room and resets is_triggered=False if the actual count no longer satisfies requirements.
    Runs asynchronously/in background to avoid blocking API startup or causing OOM memory spikes.
    """
    close_session = False
    if session is None:
        from app import Session
        session = Session()
        close_session = True

    try:
        from app.models import NotifiedItem, SlotItemCount, ThresholdGroup, DatapackageCache, UserTrackedSlot, TrackedRoom
        from sqlalchemy import func
        import json

        logging.info("[RECONCILE] Starting background SlotItemCount reconciliation...")

        # Process room by room to keep memory footprint O(1) per room
        active_rooms = session.query(TrackedRoom.id, TrackedRoom.room_id, TrackedRoom.game_checksums_json, TrackedRoom.cached_players_json).all()

        total_updated = 0
        total_reset_groups = 0

        for room_db_id, room_uuid, chk_json, p_json in active_rooms:
            # 1. Fetch actual counts for this room
            actual_counts = session.query(
                NotifiedItem.receiving_slot_id,
                NotifiedItem.item_id,
                func.count(NotifiedItem.id).label('actual_count')
            ).filter(
                NotifiedItem.room_id == room_uuid
            ).group_by(
                NotifiedItem.receiving_slot_id,
                NotifiedItem.item_id
            ).all()

            actual_map = {(s_id, i_id): cnt for s_id, i_id, cnt in actual_counts}

            # 2. Fetch existing counts for this room
            existing_counts = session.query(SlotItemCount).filter(
                SlotItemCount.room_id == room_uuid
            ).all()
            existing_map = {(c.slot_id, c.item_id): c for c in existing_counts}

            # Update or insert accurate counts
            for (s_id, i_id), actual_cnt in actual_map.items():
                if (s_id, i_id) in existing_map:
                    obj = existing_map[(s_id, i_id)]
                    if obj.count != actual_cnt:
                        obj.count = actual_cnt
                        total_updated += 1
                else:
                    session.add(SlotItemCount(
                        room_id=room_uuid,
                        slot_id=s_id,
                        item_id=i_id,
                        count=actual_cnt
                    ))
                    total_updated += 1

            # Delete orphan SlotItemCount entries for this room
            for key, obj in existing_map.items():
                if key not in actual_map:
                    session.delete(obj)
                    total_updated += 1

            # 3. Check triggered ThresholdGroups for slots in this room
            slots_in_room = session.query(UserTrackedSlot).filter(UserTrackedSlot.room_id == room_db_id).all()
            if slots_in_room:
                slot_id_to_num = {s.id: s.slot_id for s in slots_in_room}
                slot_db_ids = list(slot_id_to_num.keys())

                triggered_groups = session.query(ThresholdGroup).filter(
                    ThresholdGroup.user_tracked_slot_id.in_(slot_db_ids),
                    ThresholdGroup.is_triggered == True
                ).all()

                if triggered_groups:
                    try:
                        c_map = json.loads(chk_json or '{}')
                        p_list = json.loads(p_json or '[]')
                        game_map = {p['slot_id']: p.get('game') for p in p_list if isinstance(p, dict)}
                    except Exception:
                        c_map, game_map = {}, {}

                    cache_by_checksum = {}

                    for group in triggered_groups:
                        num_slot_id = slot_id_to_num.get(group.user_tracked_slot_id)
                        if num_slot_id is None:
                            continue

                        game_name = game_map.get(num_slot_id)
                        game_checksum = c_map.get(game_name) if game_name else None
                        if not game_checksum:
                            continue

                        if game_checksum not in cache_by_checksum:
                            name_to_id = {}
                            group_expansions = {}
                            name_results = session.query(
                                DatapackageCache.entity_name, DatapackageCache.entity_id
                            ).filter(
                                DatapackageCache.checksum == game_checksum,
                                DatapackageCache.entity_type == 'item'
                            ).all()
                            for name, eid in name_results:
                                name_to_id[name.lower().strip()] = eid

                            member_results = session.query(
                                DatapackageCache.entity_name
                            ).filter(
                                DatapackageCache.checksum == game_checksum,
                                DatapackageCache.entity_type == 'item_name_groups_json'
                            ).all()
                            for name_groups_str, in member_results:
                                try:
                                    parsed_data = json.loads(name_groups_str)
                                    if isinstance(parsed_data, dict):
                                        for g_name, items in parsed_data.items():
                                            if isinstance(items, list):
                                                group_expansions.setdefault(g_name.lower().strip(), set()).update(
                                                    item.lower().strip() for item in items
                                                )
                                except Exception:
                                    pass
                            cache_by_checksum[game_checksum] = (name_to_id, group_expansions)

                        name_to_id, group_expansions = cache_by_checksum[game_checksum]

                        all_met = True
                        for item_req in group.items:
                            if item_req.is_group:
                                members = group_expansions.get(item_req.item_name.lower().strip(), set())
                                total = 0
                                for member_name in members:
                                    m_id = name_to_id.get(member_name)
                                    if m_id is not None:
                                        total += actual_map.get((num_slot_id, m_id), 0)
                                if total < item_req.quantity:
                                    all_met = False
                                    break
                            else:
                                m_id = name_to_id.get(item_req.item_name.lower().strip())
                                if m_id is None or actual_map.get((num_slot_id, m_id), 0) < item_req.quantity:
                                    all_met = False
                                    break

                        if not all_met:
                            group.is_triggered = False
                            total_reset_groups += 1
                            logging.info(f"[RECONCILE] Reset premature triggered milestone group '{group.name or 'unnamed'}' (ID={group.id})")

            # Commit per room to keep transaction size minimal
            session.commit()

        logging.info(f"[RECONCILE] SlotItemCount background reconciliation complete: Reconciled counts={total_updated}, Reset premature groups={total_reset_groups}")
    except Exception as e:
        session.rollback()
        logging.error(f"[RECONCILE_ERROR] Failed during slot item count reconciliation: {e}", exc_info=True)
    finally:
        if close_session:
            Session.remove()

