import logging
import json
from app.models import DatapackageCache, SlotItemCount

def _resolve_slot_checksum(room, slot_id):
    """Datapackage checksum for the game a slot is playing, or None if it cannot be resolved."""
    try:
        players = json.loads(room.cached_players_json or '[]')
    except (json.JSONDecodeError, TypeError):
        return None

    game = next((p.get('game') for p in players if p.get('slot_id') == slot_id), None)
    if not game:
        return None

    try:
        checksums = json.loads(room.game_checksums_json or '{}')
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(checksums, dict):
        return None

    checksum = checksums.get(game)
    if checksum:
        return checksum

    game_lower = game.lower()
    return next(
        (v for k, v in checksums.items() if isinstance(k, str) and k.lower() == game_lower),
        None
    )


def _datapackage_lookups(session, checksum, cache):
    """
    The item name -> id map for one datapackage, memoised in `cache` (keyed by checksum) when the
    caller passes one. Loading it reads every item row for the game, so a batch over many slots of
    the same game should load it once, not once per slot.
    """
    if cache is not None and checksum in cache:
        return cache[checksum]

    name_to_id = {}
    for name, entity_id in session.query(
        DatapackageCache.entity_name, DatapackageCache.entity_id
    ).filter(
        DatapackageCache.checksum == checksum,
        DatapackageCache.entity_type == 'item'
    ).all():
        name_to_id[name.lower().strip()] = entity_id

    entry = {'name_to_id': name_to_id, 'groups': None}
    if cache is not None:
        cache[checksum] = entry
    return entry


def _item_name_groups(session, checksum, entry):
    """Every item_name_group of the datapackage as {lowercased name: set of lowercased members}, loaded once per entry."""
    if entry['groups'] is not None:
        return entry['groups']

    groups = {}
    groups_row = session.query(DatapackageCache.entity_name).filter(
        DatapackageCache.checksum == checksum,
        DatapackageCache.entity_type == 'item_name_groups_json'
    ).first()
    if groups_row and groups_row[0]:
        try:
            parsed = json.loads(groups_row[0])
            if isinstance(parsed, dict):
                # Every group is parsed, used or not, so one malformed entry must not cut the
                # loop short and drop the groups after it.
                for g_name, members in parsed.items():
                    if isinstance(g_name, str) and isinstance(members, list):
                        groups[g_name.lower().strip()] = {
                            m.lower().strip() for m in members if isinstance(m, str)
                        }
        except Exception as e:
            logging.warning(f"[MILESTONE_PROGRESS] Bad item_name_groups_json for checksum {checksum}: {e}")

    entry['groups'] = groups
    return groups


def compute_requirement_progress(session, room, slot_id, requirements, datapackage_cache=None):
    """
    Per-requirement acquired counts for one tracked slot, keyed by ThresholdGroupItem id.

    Mirrors the expansion poller._evaluate_threshold_groups performs: an item-group requirement is
    resolved against the game's item_name_groups datapackage entry and summed over every member,
    and the counts come from SlotItemCount -- the same table that decides when a milestone
    actually fires. Clients cannot do this themselves; the datapackage exposes only an is_group
    flag to them, not membership.

    A requirement is omitted from the result (rather than reported as 0) whenever its name or its
    game's datapackage cannot be resolved, so a caller can tell "nothing acquired yet" apart from
    "not knowable" and render accordingly.

    Deliberately does not heal a stale datapackage cache: this runs on a read path the Milestones
    widget calls on every refresh, and healing opens a WebSocket to the Archipelago server.

    Pass the same `datapackage_cache` dict across calls in one request to load each game's
    datapackage once rather than once per slot.
    """
    if not requirements:
        return {}

    checksum = _resolve_slot_checksum(room, slot_id)
    if not checksum:
        return {}

    lookups = _datapackage_lookups(session, checksum, datapackage_cache)
    name_to_id = lookups['name_to_id']

    group_expansions = {}
    if any(r.is_group for r in requirements):
        group_expansions = _item_name_groups(session, checksum, lookups)

    counts_by_item_id = {}
    for item_id, count in session.query(SlotItemCount.item_id, SlotItemCount.count).filter(
        SlotItemCount.room_id == room.room_id,
        SlotItemCount.slot_id == slot_id
    ).all():
        counts_by_item_id[item_id] = count

    progress = {}
    for req in requirements:
        req_key = req.item_name.lower().strip()
        if req.is_group:
            members = group_expansions.get(req_key)
            if members is None:
                continue
            total = 0
            for member_name in members:
                member_id = name_to_id.get(member_name)
                if member_id is not None:
                    total += counts_by_item_id.get(member_id, 0)
        else:
            item_id = name_to_id.get(req_key)
            if item_id is None:
                continue
            total = counts_by_item_id.get(item_id, 0)
        progress[req.id] = total

    return progress


def reconcile_slot_item_counts(session=None):
    """
    Repairs undercounts in SlotItemCount from NotifiedItem, room by room.

    Counts only move upward. NotifiedItem is purged on a retention window and
    SlotItemCount is not, so history is a floor for the true count rather than
    the value of it, and recomputing downward from it would reset milestone
    progress as soon as a room's early history aged out. The only drift this
    needs to fix is the undercount left by the legacy item_index backfill.

    Also audits triggered ThresholdGroups and resets is_triggered=False where the
    authoritative counts no longer satisfy the requirement.

    Not run automatically. The poller ran it at every start until #486; that
    repair is complete on every existing database, so it is kept only as a
    manual tool, run from the repository root:

        python -c "import sys; sys.path.insert(0, 'backend'); from app.services.threshold_service import reconcile_slot_item_counts; reconcile_slot_item_counts()"
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

            # actual_map is intentionally scoped per room iteration — keys are (slot_id, item_id)
            # without room_uuid since we rebuild it fresh each loop pass.
            actual_map = {(s_id, i_id): cnt for s_id, i_id, cnt in actual_counts}

            # 2. Fetch existing counts for this room
            existing_counts = session.query(SlotItemCount).filter(
                SlotItemCount.room_id == room_uuid
            ).all()
            existing_map = {(c.slot_id, c.item_id): c for c in existing_counts}

            # Update or insert accurate counts.
            #
            # Counts only ever move upward here, and rows absent from actual_map
            # are left alone. notified_items is purged on a retention window
            # while slot_item_counts is not, which makes NotifiedItem a floor
            # for the true count rather than the value of it. Recomputing
            # downward from it would silently reset milestone progress on every
            # long-running async multiworld the moment its early history aged
            # out, and un-trigger threshold groups that had legitimately fired.
            #
            # That makes this a repair for undercounts, which is all the legacy
            # item_index backfill this serves can cause. An overcount is not
            # reachable from here; it would need the row-level fix.
            for (s_id, i_id), actual_cnt in actual_map.items():
                if (s_id, i_id) in existing_map:
                    obj = existing_map[(s_id, i_id)]
                    if actual_cnt > obj.count:
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

            # 3. Check triggered ThresholdGroups for slots in this room.
            #
            # Audited against SlotItemCount rather than actual_map. The counts
            # are the authority that survives the retention purge; actual_map is
            # only a floor derived from whatever history has not aged out yet.
            # Auditing against the floor would un-trigger groups that fired on
            # items the player really did receive, months after the fact.
            session.flush()
            authoritative_map = {
                (s_id, i_id): cnt
                for s_id, i_id, cnt in session.query(
                    SlotItemCount.slot_id, SlotItemCount.item_id, SlotItemCount.count
                ).filter(SlotItemCount.room_id == room_uuid).all()
            }

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
                                        total += authoritative_map.get((num_slot_id, m_id), 0)
                                if total < item_req.quantity:
                                    all_met = False
                                    break
                            else:
                                m_id = name_to_id.get(item_req.item_name.lower().strip())
                                if m_id is None or authoritative_map.get((num_slot_id, m_id), 0) < item_req.quantity:
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

