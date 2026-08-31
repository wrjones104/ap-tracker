import logging
import json
from datetime import datetime
from urllib.parse import urlparse
from sqlalchemy.orm import selectinload

from app import Session
from app.models import Device, TrackedRoom, UserRoomSubscription, UserTrackedSlot
from app.utils import extract_ap_room_id, TRACK_MODE_WATCH, normalize_track_mode


def _build_player_name_map(room):
    """Slot id -> display name, from the room's cached AP player list."""
    names = {}
    try:
        for p in json.loads(room.cached_players_json or '[]'):
            slot_id = p.get('slot_id')
            if slot_id is not None:
                names[slot_id] = p.get('alias') or p.get('name')
    except (TypeError, json.JSONDecodeError, AttributeError) as err:
        logging.debug(
            "[POLLER_SYNC] Failed to parse cached players for room %s: %s", room.id, err
        )
    return names


def _build_demotion_payload(session, room, demotions):
    """
    Turns the demotions collected during a sync into the payload shape
    run_cheese_poll's push loop expects: {user_id: {'notifications': [...],
    'tokens': {platform: [token]}}}.
    """
    if not demotions:
        return {}

    user_ids = list(demotions.keys())

    tokens_by_user = {}
    for device in session.query(Device).filter(Device.user_id.in_(user_ids)).all():
        platform = (device.platform or 'android').lower().strip()
        if platform not in ['android', 'ios']:
            platform = 'android'
        tokens_by_user.setdefault(device.user_id, {}).setdefault(platform, []).append(
            device.fcm_token
        )

    aliases_by_user = {
        sub.user_id: sub.alias
        for sub in session.query(UserRoomSubscription)
        .filter(UserRoomSubscription.room_id == room.id)
        .filter(UserRoomSubscription.user_id.in_(user_ids))
        .all()
    }

    payload = {}
    for user_id, events in demotions.items():
        tokens = tokens_by_user.get(user_id)
        if not tokens or not any(tokens.values()):
            continue

        room_alias = aliases_by_user.get(user_id) or room.room_id
        notifications = []
        for player_name, reason in events:
            if reason == 'claimed':
                title = "Slot Already Claimed"
                body = (
                    f"'{player_name}' in '{room_alias}' is claimed by someone else on "
                    "Cheese Tracker. Switched to Watching — you'll still get alerts."
                )
            else:
                title = "Slot Released"
                body = (
                    f"'{player_name}' in '{room_alias}' is no longer claimed on Cheese "
                    "Tracker. Switched to Watching — you'll still get alerts."
                )
            notifications.append({'title': title, 'body': body, 'type': 'conflict'})

        payload[user_id] = {'notifications': notifications, 'tokens': tokens}

    return payload


def process_cheese_update(room_db_id, new_tracker_data, remote_updated_at):
    """
    Compares new Cheese Tracker data against local DB state, handles merging pending rooms,
    and performs bidirectional claim/unclaim synchronization with grace periods.

    Returns the push payload for any slots this sync demoted from play to watch,
    keyed by user id. Empty when nothing was demoted.
    """
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
        if not room:
            return {}
        
        is_first_sync = room.cheese_updated_at is None

        # 1. MERGE PENDING ROOMS INTO REAL ROOMS
        if room.room_id.startswith("PENDING_DISCOVERY") and new_tracker_data.get('room_link'):
            real_uuid = extract_ap_room_id(new_tracker_data['room_link'])
            if real_uuid:
                existing_real_room = session.query(TrackedRoom).filter_by(room_id=real_uuid).first()
                if existing_real_room:
                    logging.info(f"[POLLER_MERGE] Merging Pending Room {room.id} into Existing Room {existing_real_room.id}")
                    
                    pending_subs = session.query(UserRoomSubscription).filter_by(room_id=room.id).all()
                    pending_slots = session.query(UserTrackedSlot).filter_by(room_id=room.id).all()

                    ct_id_val = room.cheese_tracker_id
                    room.cheese_tracker_id = None
                    session.flush() 

                    existing_real_room.cheese_tracker_id = ct_id_val
                    
                    slots_by_user = {}
                    for s in pending_slots:
                        slots_by_user.setdefault(s.user_id, []).append(s)

                    for p_sub in pending_subs:
                        user_id = p_sub.user_id
                        real_sub = session.query(UserRoomSubscription).filter_by(
                            user_id=user_id, room_id=existing_real_room.id
                        ).first()
                        
                        if not real_sub:
                            real_sub = UserRoomSubscription(
                                user_id=user_id, 
                                room_id=existing_real_room.id,
                                alias=p_sub.alias,
                                is_archived=p_sub.is_archived
                            )
                            session.add(real_sub)
                            session.flush()

                        user_slots = slots_by_user.get(user_id, [])
                        for p_slot in user_slots:
                            conflict_slot = session.query(UserTrackedSlot).filter_by(
                                 user_id=user_id, room_id=existing_real_room.id, slot_id=p_slot.slot_id
                            ).first()
                            
                            if conflict_slot:
                                session.delete(p_slot)
                            else:
                                p_slot.room_id = existing_real_room.id

                        session.delete(p_sub)
                    
                    session.delete(room)
                    session.commit() 
                    room = existing_real_room
                else:
                    logging.info(f"[POLLER_HEAL] Updating Pending Room {room.id} to UUID {real_uuid}")
                    room.room_id = real_uuid
                    try:
                        parsed = urlparse(new_tracker_data['room_link'])
                        if parsed.hostname:
                            room.hostname = parsed.hostname
                            room.cached_full_address = f"{parsed.hostname}:{new_tracker_data.get('last_port', '')}"
                    except Exception:
                        pass

        # 2. UPDATE DB CACHE
        room.cached_cheese_json = json.dumps(new_tracker_data)
        
        try:
            clean_time = remote_updated_at
            if '.' in clean_time:
                main, frac = clean_time.split('.')
                clean_time = f"{main}.{frac[:6]}"
            parsed_dt = datetime.fromisoformat(clean_time.replace('Z', '+00:00'))
            if parsed_dt.tzinfo:
                parsed_dt = parsed_dt.replace(tzinfo=None)
            room.cheese_updated_at = parsed_dt
        except (ValueError, TypeError):
            room.cheese_updated_at = datetime.utcnow()

        # 3. UNCLAIM SYNC
        new_games_map = {g['position']: g for g in new_tracker_data.get('games', [])}
        current_tracked_slots = session.query(UserTrackedSlot).options(
            selectinload(UserTrackedSlot.user)
        ).filter_by(room_id=room.id).all()

        # {user_id: [(player_name, reason)]} for slots this sync demotes.
        # 'claimed' and 'released' are kept apart because an auto-release the
        # user opted into should not read as someone taking their slot.
        demotions = {}
        player_names = _build_player_name_map(room)

        for ts in current_tracked_slots:
            user = ts.user
            if not user or not user.cheese_user_id:
                continue

            # Watch slots are alerts-only. Who owns the slot on Cheese is
            # explicitly not their concern, so the sync never demotes, unclaims
            # or drops them -- including the vanished-slot branch below, since a
            # watch slot's alerts come from the AP room, not from Cheese.
            #
            # Note this is one-way: once a slot lands here the poller skips it
            # forever, and a manual sync will not re-promote it either. Only an
            # explicit switch back to Playing in the picker restores the claim.
            if normalize_track_mode(ts.track_mode) == TRACK_MODE_WATCH:
                continue

            game_data = new_games_map.get(ts.slot_id)

            if game_data:
                remote_owner_id = game_data.get('claimed_by_ct_user_id')
                claim_discord = game_data.get('effective_discord_username') or game_data.get('discord_username')
                claim_discord_clean = claim_discord.strip().lower() if claim_discord else None
                my_discord_clean = user.discord_username.strip().lower() if user.discord_username else None

                is_other_auth_claim = (remote_owner_id is not None and remote_owner_id != user.cheese_user_id)
                is_other_unauth_claim = (remote_owner_id is None and claim_discord_clean is not None and (my_discord_clean is None or claim_discord_clean != my_discord_clean))

                # Losing a claim demotes the slot to watch; it never deletes it.
                # The user keeps their alerts, thresholds and per-slot prefs and
                # simply stops owning the slot on Cheese.
                if is_other_auth_claim or is_other_unauth_claim:
                    logging.info(f"[POLLER_SYNC] Demoting Slot {ts.slot_id} to watch (Owner mismatch: remote_owner_id={remote_owner_id}, claim_discord={claim_discord})")
                    ts.track_mode = TRACK_MODE_WATCH
                    demotions.setdefault(ts.user_id, []).append(
                        (player_names.get(ts.slot_id) or f"Slot {ts.slot_id}", 'claimed')
                    )
                elif remote_owner_id is None and claim_discord_clean is None:
                    if is_first_sync:
                        logging.info(f"[POLLER_SYNC] GRACE PERIOD: Keeping Slot {ts.slot_id} (First Sync).")
                        continue
                    # Covers auto-release: the host's tracker released the slot
                    # out from under a player who still wants to watch it.
                    logging.info(f"[POLLER_SYNC] Demoting Slot {ts.slot_id} to watch (Remote is unclaimed).")
                    ts.track_mode = TRACK_MODE_WATCH
                    demotions.setdefault(ts.user_id, []).append(
                        (player_names.get(ts.slot_id) or f"Slot {ts.slot_id}", 'released')
                    )
            else:
                if is_first_sync:
                    logging.info(f"[POLLER_SYNC] GRACE PERIOD: Keeping Slot {ts.slot_id} (Slot missing - First Sync).")
                    continue
                # The slot no longer exists on the tracker at all -- there is
                # nothing left to own or to watch.
                logging.info(f"[POLLER_SYNC] Untracking Slot {ts.slot_id} (Slot vanished from Cheese)")
                session.delete(ts)

        # Built before the commit so the room and subscription rows are still
        # loaded; the poller only sends after this function returns.
        payload = _build_demotion_payload(session, room, demotions)

        session.commit()
        return payload

    except Exception as e:
        logging.error(f"[POLLER_CHEESE_ERROR] DB Update failed: {e}", exc_info=True)
        session.rollback()
        return {}
    finally:
        Session.remove()
