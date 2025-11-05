import asyncio
import logging
import aiohttp
import json
import websockets
from datetime import datetime, timezone, timedelta
from threading import local
from sqlalchemy import or_, exc, tuple_  # <-- Added tuple_
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import OperationalError, IntegrityError

from . import Session, get_firebase_app, process
from .models import (
    User, Device, TrackedRoom, UserRoomSubscription, UserTrackedSlot,
    DatapackageCache, NotifiedItem, NotifiedHint
)

from . import POLLING_INTERVAL_SECONDS, SUPERVISOR_INTERVAL_SECONDS

thread_local_data = local()

async def close_aiohttp_session():
    session = getattr(thread_local_data, "aiohttp_session", None)
    if session:
        await session.close()
        logging.info("[POLLER] Aiohttp session closed.")
    if hasattr(thread_local_data, "aiohttp_session"):
        del thread_local_data.aiohttp_session

def get_aiohttp_session():
    if not hasattr(thread_local_data, "aiohttp_session") or thread_local_data.aiohttp_session.closed:
        thread_local_data.aiohttp_session = aiohttp.ClientSession()
    return thread_local_data.aiohttp_session

def log_resource_usage(app):
    """Logs the current CPU and Memory usage of this script."""
    if not app.config.get('DEBUG'): return
    cpu_usage = process.cpu_percent(interval=None)
    memory_info = process.memory_info()
    memory_mb = memory_info.rss / (1024 * 1024)
    logging.debug(f"[RESOURCES] CPU: {cpu_usage:.2f}% | Memory: {memory_mb:.2f} MB")

async def send_push_notifications(notifications, device_tokens, loop):
    firebase_app = get_firebase_app()
    if not firebase_app or not notifications or not device_tokens: return

    from firebase_admin import messaging

    messages = []
    for content in notifications:
        try:
            logging.info(f"[NOTIFIER] Preparing notification for {len(device_tokens)} devices. Title: {content['title']} | Body: {content['body']}")
        except Exception as e:
            logging.error(f"[NOTIFIER] Error creating log message: {e}")
        for token in device_tokens:
            android_config = messaging.AndroidConfig(priority='high')
            messages.append(messaging.Message(
                notification=messaging.Notification(title=content['title'], body=content['body']),
                token=token, android=android_config
            ))
    if not messages: return

    for i in range(0, len(messages), 10):
        chunk = messages[i:i + 10]
        try:
            logging.info(f"[FCM] Sending a chunk of {len(chunk)} messages...")
            response = await loop.run_in_executor(None, lambda: messaging.send_each(chunk))
            
            unregistered_tokens = []
            for idx, res in enumerate(response.responses):
                if not res.success:
                    error_code = res.exception.code if hasattr(res.exception, 'code') else "UNKNOWN"
                    if error_code in ['UNREGISTERED', 'NOT_FOUND']:
                        unregistered_tokens.append(chunk[idx].token)

            if unregistered_tokens:
                logging.info(f"[FCM] Found {len(unregistered_tokens)} invalid devices. Removing from DB.")
                await loop.run_in_executor(None, db_remove_invalid_tokens, unregistered_tokens)
                
        except Exception as e:
            logging.error(f"[FCM] A critical error occurred while sending a chunk: {e}", exc_info=True)
        if i + 10 < len(messages):
            await asyncio.sleep(1)

def db_remove_invalid_tokens(tokens_to_remove):
    """Synchronously removes invalid FCM tokens from the database."""
    session = Session()
    try:
        session.query(Device).filter(Device.fcm_token.in_(tokens_to_remove)).delete(synchronize_session=False)
        session.commit()
    except Exception as e:
        logging.error(f"[FCM_DB_ERROR] Error removing invalid tokens: {e}")
        session.rollback()
    finally:
        Session.remove()

async def fetch_json(url):
    session = get_aiohttp_session()
    try:
        async with session.get(url, timeout=15) as response:
            response.raise_for_status()
            return await response.json()
    except Exception as e:
        return None

async def run_room_poll(room_info, loop):
    """
    Runs a single lightweight poll cycle for an *already set up* room.
    All DB logic is deferred to an executor.
    """
    db_id = room_info['db_id']
    hostname = room_info['hostname']
    
    room_data = await loop.run_in_executor(None, db_read_room_poll_state, db_id)
    if not room_data:
        logging.warning(f"[POLLER][RoomDBID:{db_id}] Room not found during poll read.")
        return
        
    tracker_id = room_data['tracker_id']
    room_uuid = room_data['room_uuid']

    if not tracker_id:
        logging.warning(f"[POLLER_WARN][RoomDBID:{db_id}] No tracker_id, cannot poll. Setup may be needed.")
        return

    tracker_data = await fetch_json(f"https://{hostname}/api/tracker/{tracker_id}")

    try:
        notifications_to_send = await loop.run_in_executor(
            None, 
            db_process_poll_data, 
            db_id, 
            room_uuid, 
            tracker_data, 
            room_data 
        )
        
        if notifications_to_send:
            for user_id, data in notifications_to_send.items():
                logging.info(f"[NOTIFY] Sending {len(data['notifications'])} notification(s) to user {user_id} for room '{data['alias']}'")
                await send_push_notifications(data['notifications'], data['tokens'], loop)

    except Exception as e:
        logging.error(f"[POLLER_ERROR][RoomDBID:{db_id}] An unhandled exception occurred in run_room_poll!", exc_info=True)

def db_read_room_poll_state(db_id):
    """Synchronously fetches the minimal data needed to run a poll."""
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=db_id).first()
        if not room:
            return None
            
        return {
            'room_uuid': room.room_id,
            'tracker_id': room.tracker_id,
            'cached_players_json_str': room.cached_players_json,
            'game_checksums_json_str': room.game_checksums_json,
            'is_complete_status': room.is_complete
        }
    except Exception as e:
        logging.error(f"[POLLER_DB_ERROR][RoomDBID:{db_id}] Failed to read poll state: {e}", exc_info=True)
        return None
    finally:
        Session.remove()

def db_process_poll_data(db_id, room_uuid, tracker_data, room_data):
    """
    Synchronously processes tracker data and updates the database.
    This contains the main polling logic from the old function.
    Returns a dict of notifications to send.
    """
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=db_id).first()
        if not room: 
            logging.warning(f"[POLLER_DB_ERROR][RoomDBID:{db_id}] Room vanished before poll processing.")
            return

        if not tracker_data:
            room.failed_poll_count += 1
            if room.failed_poll_count >= 20: room.is_suspended = True
            session.commit()
            return

        room.failed_poll_count = 0
        room.last_successful_poll = datetime.utcnow()
        
        cached_players_json_str = room_data['cached_players_json_str']
        game_checksums_json_str = room_data['game_checksums_json_str']
        is_complete_status = room_data['is_complete_status']
        
        players = json.loads(cached_players_json_str if cached_players_json_str else '[]')
        game_checksums = json.loads(game_checksums_json_str if game_checksums_json_str else '{}')
        name_map = {p['slot_id']: p['name'] for p in players}
        game_map = {p['slot_id']: p['game'] for p in players}

        has_item_history = session.query(NotifiedItem.id).filter_by(room_id=room_uuid).limit(1).scalar() is not None
        has_hint_history = session.query(NotifiedHint.id).filter_by(room_id=room_uuid).limit(1).scalar() is not None

        existing_items_in_db = set(session.query(NotifiedItem.receiving_slot_id, NotifiedItem.item_id, NotifiedItem.location_id).filter_by(room_id=room_uuid))
        
        # REFACTOR: Get a map of all existing hints and their objects
        existing_hints_map = {
            (h.item_owner_id, h.location_owner_id, h.item_id, h.location_id): h
            for h in session.query(NotifiedHint).filter_by(room_id=room_uuid)
        }

        all_tracked_slots_in_room = session.query(UserTrackedSlot).filter_by(room_id=db_id).all()
        if not all_tracked_slots_in_room:
             session.commit()
             return

        tracked_slots_by_user = {}
        prefs_by_user_slot = {}
        all_user_ids_in_room = set()
        
        for slot in all_tracked_slots_in_room:
            tracked_slots_by_user.setdefault(slot.user_id, set()).add(slot.slot_id)
            prefs_by_user_slot.setdefault(slot.user_id, {})[slot.slot_id] = slot
            all_user_ids_in_room.add(slot.user_id)

        users_by_id = {u.id: u for u in session.query(User).filter(User.id.in_(all_user_ids_in_room))}
        aliases_by_user = { sub.user_id: sub.alias for sub in session.query(UserRoomSubscription).filter(UserRoomSubscription.user_id.in_(all_user_ids_in_room), UserRoomSubscription.room_id == db_id) }

        notifications_by_user = {} 

        cache_keys_to_fetch = set()
        new_items_for_notify = []
        new_hints_for_notify = []
        # REFACTOR: This set will hold (loc_id, item_id) for items linked to a "just found" hint
        just_found_hint_item_loc_pairs = set()

        player_statuses_raw = tracker_data.get('player_status', {})
        finished_player_ids = set()
        if isinstance(player_statuses_raw, dict): finished_player_ids = {int(p) for p, s in player_statuses_raw.items() if s == 30}
        elif isinstance(player_statuses_raw, list):
             for status_info in player_statuses_raw:
                 if isinstance(status_info, dict) and status_info.get('status') == 30 and 'player' in status_info:
                     finished_player_ids.add(status_info.get('player'))

        if finished_player_ids:
            players_to_untrack_by_user = {} 
            for user_id, tracked_slots in tracked_slots_by_user.items():
                for slot_id in finished_player_ids:
                    if slot_id in tracked_slots:
                        players_to_untrack_by_user.setdefault(user_id, []).append(
                            name_map.get(slot_id, f"Player {slot_id}")
                        )

            for user_id, names in players_to_untrack_by_user.items():
                player_names_str = ", ".join(names)
                alias = aliases_by_user.get(user_id, "Unknown Room")
                notifications_by_user.setdefault(user_id, []).append({
                    'title': f"🏁 Player(s) Finished!",
                    'body': f"{player_names_str} finished in '{alias}'. Slot(s) untracked.",
                    'type': 'player_finish',
                    'details': (room_uuid, user_id, player_names_str)
                })

        deleted_count = 0
        if finished_player_ids:
            deleted_count = session.query(UserTrackedSlot).filter(
                UserTrackedSlot.room_id == db_id,
                UserTrackedSlot.slot_id.in_(finished_player_ids)
            ).delete(synchronize_session=False)
            if deleted_count > 0:
                logging.info(f"[POLLER_ACTION][RoomDBID:{db_id}] Automatically untracked {deleted_count} finished player(s).")

        total_players = len(players)
        if total_players > 0 and len(finished_player_ids) >= total_players:
            if not is_complete_status:
                room.is_complete = True
                logging.info(f"[POLLER_ACTION][RoomDBID:{db_id}] Room marked as complete.")

        items_to_add_to_db = []
        hints_to_add_to_db = []
        items_in_this_batch = set()
        hints_in_this_batch = set()

        items_processed_count = 0
        items_skipped_classification = 0
        items_skipped_duplicate = 0
        items_added_count = 0
        added_items_details = [] 
        
        items_skipped_backfill = 0

        # REFACTOR: This block is no longer needed for hint processing,
        # but we keep it for debugging/logging item processing.
        all_received_item_loc_pairs = set()
        for p_items in tracker_data.get('player_items_received', []):
            for item_tuple_data in p_items.get('items', []):
                try:
                    if len(item_tuple_data) < 4: continue
                    item_id, loc_id, _, _ = item_tuple_data 
                    all_received_item_loc_pairs.add((loc_id, item_id))
                except (ValueError, TypeError, IndexError):
                    continue
        
        if all_received_item_loc_pairs:
             logging.debug(f"[POLLER_HINT_DEBUG][RoomDBID:{db_id}] Found {len(all_received_item_loc_pairs)} total (loc_id, item_id) pairs in 'player_items_received'.")

        for p_items in tracker_data.get('player_items_received', []):
            rid = p_items.get('player')
            if not isinstance(rid, int): continue

            is_tracked_by_anyone = False
            for tracked_slots in tracked_slots_by_user.values():
                if rid in tracked_slots:
                    is_tracked_by_anyone = True
                    break
            if not is_tracked_by_anyone:
                continue

            for item_tuple_data in p_items.get('items', []):
                items_processed_count += 1
                try:
                    if len(item_tuple_data) < 4: continue
                    item_id, loc_id, send_id, flags = item_tuple_data
                    item_id = int(item_id)
                    loc_id = int(loc_id)
                    send_id = int(send_id)
                except (ValueError, TypeError, IndexError) as e:
                    logging.warning(f"[POLLER_WARN][RoomDBID:{db_id}] Error unpacking item tuple: {item_tuple_data} | Error: {e}")
                    continue 

                item_key_db = (rid, item_id, loc_id)
                item_key_batch = (room_uuid, rid, item_id, loc_id) 

                if (item_key_db in existing_items_in_db) or (item_key_batch in items_in_this_batch):
                    items_skipped_duplicate += 1
                    continue

                if not (flags & 1 or flags & 2):
                    items_skipped_classification += 1
                    continue

                items_to_add_to_db.append(NotifiedItem(
                    room_id=room_uuid,
                    receiving_slot_id=rid,
                    item_id=item_id,
                    location_id=loc_id
                ))
                items_in_this_batch.add(item_key_batch)
                items_added_count += 1
                added_items_details.append(f"(Slot:{rid}, Item:{item_id}, Loc:{loc_id})")

                if has_item_history: 
                    receiver_game = game_map.get(rid, "Unknown")
                    game_checksum = game_checksums.get(receiver_game)

                    if game_checksum:
                        cache_keys_to_fetch.add((receiver_game, game_checksum, 'item', item_id))

                    sender_game = game_map.get(send_id, "Unknown")
                    sender_checksum = game_checksums.get(sender_game)
                    if sender_checksum:
                        cache_keys_to_fetch.add((sender_game, sender_checksum, 'location', loc_id))
                    
                    new_items_for_notify.append({
                        'item_key_batch': item_key_batch,
                        'receiving_slot_id': rid,
                        'sending_slot_id': send_id,
                        'item_id': item_id,
                        'location_id': loc_id,
                        'flags': flags,
                        'receiver_game': receiver_game,
                        'game_checksum': game_checksum,
                        'sender_game': sender_game,
                        'sender_checksum': sender_checksum
                    })
                else:
                    items_skipped_backfill += 1

        if items_processed_count > 0: 
             added_items_log_str = ", ".join(added_items_details) if added_items_details else "None"
             logging.debug(f"[POLLER_DEBUG][RoomDBID:{db_id}] Item Stats: Processed={items_processed_count}, Skipped (Class)={items_skipped_classification}, Skipped (Dupe)={items_skipped_duplicate}, Added={items_added_count} | New Items: [{added_items_log_str}]")

        if items_skipped_backfill > 0:
            logging.info(f"[POLLER_INFO][RoomDBID:{db_id}] Suppressed {items_skipped_backfill} item notifications during initial backfill.")

        hints_processed_count = 0
        hints_added_count = 0
        hints_skipped_backfill = 0
        
        for p_hints in tracker_data.get('hints', []):
             for hint_data in p_hints.get('hints', []):
                hints_processed_count += 1
                try:
                    if len(hint_data) < 5: continue 
                    io_id, lo_id, loc_id, item_id, is_found_from_tracker, *_ = hint_data
                    io_id = int(io_id)
                    lo_id = int(lo_id)
                    loc_id = int(loc_id)
                    item_id = int(item_id)
                    is_found_from_tracker = bool(is_found_from_tracker) 
                except (ValueError, IndexError):
                    logging.warning(f"[POLLER_WARN][RoomDBID:{db_id}] Error unpacking hint tuple: {hint_data}")
                    continue

                hint_key_db = (io_id, lo_id, item_id, loc_id)
                hint_key_batch = (room_uuid, io_id, lo_id, item_id, loc_id)

                existing_hint_obj = existing_hints_map.get(hint_key_db)

                if not existing_hint_obj:
                    if hint_key_batch in hints_in_this_batch: continue
                    
                    hints_to_add_to_db.append(NotifiedHint(
                        room_id=room_uuid,
                        item_owner_id=io_id,
                        location_owner_id=lo_id,
                        item_id=item_id,
                        location_id=loc_id,
                        is_found=is_found_from_tracker
                    ))
                    hints_in_this_batch.add(hint_key_batch)
                    hints_added_count += 1

                    if has_hint_history:
                        io_game, lo_game = game_map.get(io_id, "Unknown"), game_map.get(lo_id, "Unknown")
                        io_checksum = game_checksums.get(io_game)
                        lo_checksum = game_checksums.get(lo_game)

                        if io_checksum:
                            cache_keys_to_fetch.add((io_game, io_checksum, 'item', item_id))
                        if lo_checksum:
                            cache_keys_to_fetch.add((lo_game, lo_checksum, 'location', loc_id))
                        
                        new_hints_for_notify.append({
                            'hint_key_batch': hint_key_batch,
                            'io_id': io_id, 'lo_id': lo_id, 'item_id': item_id, 'loc_id': loc_id,
                            'io_game': io_game, 'lo_game': lo_game,
                            'io_checksum': io_checksum, 'lo_checksum': lo_checksum
                        })
                        
                        if is_found_from_tracker:
                            logging.debug(f"[POLLER_HINT_DEBUG][RoomDBID:{db_id}] New hint {hint_key_db} is already found.")
                            just_found_hint_item_loc_pairs.add((loc_id, item_id))
                    else:
                        hints_skipped_backfill += 1
                
                else:
                    if is_found_from_tracker and not existing_hint_obj.is_found:
                        logging.debug(f"[POLLER_HINT_DEBUG][RoomDBID:{db_id}] Existing hint {hint_key_db} marked as found.")
                        existing_hint_obj.is_found = True # Mark for update in the session
                        just_found_hint_item_loc_pairs.add((loc_id, item_id))
        
        if hints_processed_count > 0:
             logging.debug(f"[POLLER_DEBUG][RoomDBID:{db_id}] Hint Stats: Processed={hints_processed_count}, Added={hints_added_count}")
             if just_found_hint_item_loc_pairs:
                 logging.info(f"[POLLER_ACTION][RoomDBID:{db_id}] Detected {len(just_found_hint_item_loc_pairs)} hints that were just found.")


        if hints_skipped_backfill > 0:
            logging.info(f"[POLLER_INFO][RoomDBID:{db_id}] Suppressed {hints_skipped_backfill} hint notifications during initial backfill.")


        
        name_lookup_map = {}
        if cache_keys_to_fetch:
            logging.debug(f"[POLLER_DEBUG][RoomDBID:{db_id}] Fetching {len(cache_keys_to_fetch)} names from DatapackageCache...")
            try:
                results = session.query(
                    DatapackageCache.game,
                    DatapackageCache.checksum,
                    DatapackageCache.entity_type,
                    DatapackageCache.entity_id,
                    DatapackageCache.entity_name
                ).filter(
                    tuple_(
                        DatapackageCache.game,
                        DatapackageCache.checksum,
                        DatapackageCache.entity_type,
                        DatapackageCache.entity_id
                    ).in_(cache_keys_to_fetch)
                )
                
                for game, chk, etype, eid, name in results:
                    name_lookup_map[(game, chk, etype, eid)] = name
            
            except Exception as e:
                logging.error(f"[POLLER_DB_ERROR][RoomDBID:{db_id}] Failed to bulk-fetch names: {e}")

        for item_data in new_items_for_notify:
            item_name = name_lookup_map.get(
                (item_data['receiver_game'], item_data['game_checksum'], 'item', item_data['item_id']), 
                f"ID {item_data['item_id']}"
            )
            
            loc_name = name_lookup_map.get(
                (item_data['sender_game'], item_data['sender_checksum'], 'location', item_data['location_id']),
                f"ID {item_data['location_id']}"
            )
            
            item_id = item_data['item_id']
            loc_id = item_data['location_id']
            is_a_found_hint = (loc_id, item_id) in just_found_hint_item_loc_pairs
            
            rid = item_data['receiving_slot_id']
            send_id = item_data['sending_slot_id']

            for user_id, tracked_slots in tracked_slots_by_user.items():
                if rid in tracked_slots:
                    alias = aliases_by_user.get(user_id, "Unknown Room")
                    
                    user_prefs = users_by_id.get(user_id)
                    slot_prefs = prefs_by_user_slot.get(user_id, {}).get(rid)

                    if not user_prefs or not slot_prefs:
                        logging.warning(f"[NOTIFY_SKIP][RoomDBID:{db_id}] Could not find user/slot prefs for user {user_id}, slot {rid}.")
                        continue

                    if slot_prefs.added_at and datetime.utcnow() - slot_prefs.added_at < timedelta(minutes=2):
                        logging.info(f"[NOTIFY_SKIP][RoomDBID:{db_id}] User {user_id} is tracking Slot {rid}, but it was added at {slot_prefs.added_at}. Suppressing notification for item {item_data['item_id']}.")
                        continue

                    is_progression = bool(item_data['flags'] & 1)
                    should_notify = False
                    title_prefix = ""
                    item_type = ""
                    
                    if is_progression:
                        title_prefix = f"🏆 {item_name}"
                        item_type = "item_progression"
                        notify_override = slot_prefs.notify_progression
                        should_notify = notify_override if notify_override is not None else user_prefs.notify_progression_default
                    else:
                        title_prefix = f"✅ {item_name}"
                        item_type = "item_useful"
                        notify_override = slot_prefs.notify_useful
                        should_notify = notify_override if notify_override is not None else user_prefs.notify_useful_default
                    
                    if is_a_found_hint:
                        title_prefix = "💡 " + title_prefix
                    
                    title = f"{title_prefix} - [{alias}]"
                    
                    sender_name = name_map.get(send_id, f'P{send_id}')
                    receiver_name = name_map.get(rid, f'P{rid}')
                    
                    body = f"{sender_name} sent {item_name} to {receiver_name} ({loc_name})"
                    
                    if should_notify:
                        notifications_by_user.setdefault(user_id, []).append({
                            'title': title,
                            'body': body,
                            'type': item_type,
                            'details': item_data['item_key_batch']
                        })

        for hint_data in new_hints_for_notify:
            item_name = name_lookup_map.get(
                (hint_data['io_game'], hint_data['io_checksum'], 'item', hint_data['item_id']),
                f"ID {hint_data['item_id']}"
            )
            loc_name = name_lookup_map.get(
                (hint_data['lo_game'], hint_data['lo_checksum'], 'location', hint_data['loc_id']),
                f"ID {hint_data['loc_id']}"
            )
            
            io_id, lo_id = hint_data['io_id'], hint_data['lo_id']
            for user_id, tracked_slots in tracked_slots_by_user.items():
                is_for_us, is_at_our_location = io_id in tracked_slots, lo_id in tracked_slots
                if is_for_us or is_at_our_location:
                    
                    slot_to_check = io_id if is_for_us else lo_id
                    
                    user_prefs = users_by_id.get(user_id)
                    slot_prefs = prefs_by_user_slot.get(user_id, {}).get(slot_to_check)

                    if not user_prefs or not slot_prefs:
                        logging.warning(f"[NOTIFY_SKIP][RoomDBID:{db_id}] Could not find user/slot prefs for hint, user {user_id}, slot {slot_to_check}.")
                        continue

                    if slot_prefs.added_at and datetime.utcnow() - slot_prefs.added_at < timedelta(minutes=2):
                        logging.info(f"[NOTIFY_SKIP][RoomDBID:{db_id}] User {user_id} tracking Slot {slot_to_check} added at {slot_prefs.added_at}. Suppressing hint notification.")
                        continue
                    
                    notify_override = slot_prefs.notify_hints
                    should_notify = notify_override if notify_override is not None else user_prefs.notify_progression_default
                    
                    if not should_notify:
                        continue

                    alias = aliases_by_user.get(user_id, "Unknown Room")
                    
                    title = f"💡 New Hint! - [{alias}]"

                    item_owner_name = name_map.get(io_id, f'P{io_id}')
                    location_owner_name = name_map.get(lo_id, f'P{lo_id}')

                    body = f"{item_owner_name}'s {item_name} is at {loc_name} in {location_owner_name}'s World."

                    notifications_by_user.setdefault(user_id, []).append({'title': title, 'body': body, 'type': 'hint', 'details': hint_data['hint_key_batch']})
    
        if hints_skipped_backfill > 0:
            logging.info(f"[POLLER_INFO][RoomDBID:{db_id}] Suppressed {hints_skipped_backfill} hint notifications during initial backfill.")
       
        elif items_added_count > 0:
            logging.info(f"[NOTIFY_SKIP][RoomDBID:{db_id}] Added {items_added_count} new items, but no notifications were queued (e.g., all suppressed or no users tracking).")

        if items_to_add_to_db:
            session.bulk_save_objects(items_to_add_to_db)
            if not has_item_history:
                logging.info(f"[POLLER][RoomDBID:{db_id}] Silently backfilled {len(items_to_add_to_db)} historical items (Progression/Useful).")
            elif not notifications_by_user: 
                logging.info(f"[POLLER][RoomDBID:{db_id}] Silently added {len(items_to_add_to_db)} new items (Progression/Useful).")

        if hints_to_add_to_db:
            session.bulk_save_objects(hints_to_add_to_db)
            if not has_hint_history:
                logging.info(f"[POLLER][RoomDBID:{db_id}] Silently backfilled {len(hints_to_add_to_db)} historical hints.")
            elif not notifications_by_user: 
                 logging.info(f"[POLLER][RoomDBID:{db_id}] Silently added {len(hints_to_add_to_db)} new hints.")


        notifications_to_send = {}
        if notifications_by_user:
            all_user_ids = notifications_by_user.keys()
            devices_to_notify = session.query(Device).filter(Device.user_id.in_(all_user_ids)).all()
            tokens_by_user = {}
            for device in devices_to_notify: tokens_by_user.setdefault(device.user_id, []).append(device.fcm_token)

            for user_id, notifications in notifications_by_user.items():
                user_tokens = tokens_by_user.get(user_id)
                if user_tokens:
                    unique_notifications = list({json.dumps(d): d for d in notifications}.values())
                    notifications_to_send[user_id] = {
                        'notifications': unique_notifications,
                        'tokens': user_tokens,
                        'alias': aliases_by_user.get(user_id)
                    }
                else:
                    logging.warning(f"[NOTIFY_SKIP][RoomDBID:{db_id}] User {user_id} had {len(notifications)} notifications queued, but has NO registered device tokens.")

        session.commit()
        return notifications_to_send

    except OperationalError as oe: 
        logging.error(f"[POLLER_ERROR][RoomDBID:{db_id}] Database was locked during main poll. Skipping cycle. Error: {oe}")
        session.rollback()
    except Exception as e:
        logging.error(f"[POLLER_ERROR][RoomDBID:{db_id}] An unhandled exception occurred in db_process_poll_data!", exc_info=True)
        session.rollback()
    finally:
        Session.remove()
    return None


async def run_room_setup(room_info, loop):
    """
    Performs the heavy, memory-intensive setup for a single new room.
    All DB logic is deferred to an executor.
    """
    db_id = room_info['db_id']
    hostname = room_info['hostname']
    room_uuid = room_info['room_uuid']
    
    logging.info(f"[POLLER_SETUP][RoomDBID:{db_id}] Starting setup...")
    
    setup_data = {} 
    
    try:
        room_status = await fetch_json(f"https://{hostname}/api/room_status/{room_uuid}")
        if not room_status:
            logging.error(f"[POLLER_SETUP_ERROR][RoomDBID:{db_id}] Failed to fetch room status.")
            return

        players_raw = room_status.get('players', [])
        player_list = [{'slot_id': i + 1, 'name': p[0], 'game': p[1]} for i, p in enumerate(players_raw)]
        setup_data['cached_players_json'] = json.dumps(player_list)
        setup_data['cached_total_slots'] = len(player_list)
        setup_data['cached_full_address'] = f"{hostname}:{room_status.get('last_port', '')}"
        setup_data['last_api_check'] = datetime.utcnow()

        new_tracker_id = room_status.get('tracker')
        if not new_tracker_id:
            logging.warning(f"[POLLER_SETUP_WARN][RoomDBID:{db_id}] No tracker ID found in status. Will retry.")
        else:
            setup_data['tracker_id'] = new_tracker_id

        port = room_status.get('last_port')
        checksums = {}

        if port:
            uri = f"wss://{hostname}:{port}"
            try:
                async with websockets.connect(uri, open_timeout=5) as ws:
                    msg_str = await asyncio.wait_for(ws.recv(), timeout=5)
                    room_info_msg = json.loads(msg_str)
                    checksums = room_info_msg[0].get('datapackage_checksums', {})
            except Exception as ws_e:
                logging.warning(f"[POLLER_SETUP_WARN][RoomDBID:{db_id}] Failed to get checksums from WebSocket: {ws_e}")
                checksums = room_status.get('datapackage_checksums', {})
        else:
            checksums = room_status.get('datapackage_checksums', {})

        new_checksums_json_str = json.dumps(checksums)
        datapackage_entries_by_game = {}

        if checksums:
            logging.debug(f"[POLLER_SETUP_DEBUG][RoomDBID:{db_id}] New/updated checksums found. Fetching datapackages...")
            
            checksums_to_check = set(checksums.values())
            
            existing_in_db = await loop.run_in_executor(
                None, 
                db_check_existing_checksums, 
                checksums_to_check
            )
            
            new_checksums_to_fetch = checksums_to_check - existing_in_db

            for game, checksum in checksums.items():
                if checksum in new_checksums_to_fetch: 
                    game_data = await fetch_json(f"https://{hostname}/api/datapackage/{checksum}")
                    if not game_data: continue
                    
                    current_game_entries = []
                    actual_data = game_data.get('games', {}).get(game, game_data)
                    for n, eid in actual_data.get('item_name_to_id', {}).items():
                        current_game_entries.append(DatapackageCache(game=game, checksum=checksum, entity_type='item', entity_id=eid, entity_name=n))
                    for n, eid in actual_data.get('location_name_to_id', {}).items():
                        current_game_entries.append(DatapackageCache(game=game, checksum=checksum, entity_type='location', entity_id=eid, entity_name=n))
                    
                    if current_game_entries:
                        datapackage_entries_by_game[game] = current_game_entries
            
            if datapackage_entries_by_game:
                setup_data['datapackage_entries_by_game'] = datapackage_entries_by_game
            
            setup_data['game_checksums_json'] = new_checksums_json_str

        setup_data['is_setup'] = True 
        logging.info(f"[POLLER_SETUP][RoomDBID:{db_id}] Setup network fetch complete.")

    except Exception as e:
        logging.error(f"[POLLER_SETUP_ERROR][RoomDBID:{db_id}] Unhandled setup network error: {e}", exc_info=True)
        return 

    try:
        await loop.run_in_executor(None, db_commit_setup_data, db_id, setup_data)
        logging.info(f"[POLLER_SETUP][RoomDBID:{db_id}] Setup data committed to DB.")
    except Exception as e:
        logging.error(f"[POLLER_SETUP_ERROR][RoomDBID:{db_id}] Failed to commit setup data: {e}", exc_info=True)

def db_check_existing_checksums(checksums_to_check):
    """Synchronously checks which of the given checksums are already in the cache."""
    session = Session()
    try:
        existing = set(
            c[0] for c in session.query(DatapackageCache.checksum)
            .filter(DatapackageCache.checksum.in_(checksums_to_check))
            .distinct()
        )
        return existing
    except Exception as e:
        logging.error(f"[POLLER_DB_ERROR] Failed to check existing checksums: {e}")
        return set()
    finally:
        Session.remove()

def db_commit_setup_data(db_id, setup_data):
    """
    Synchronously commits all setup data to the database in a single transaction block.
    """
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=db_id).first()
        if not room: 
            logging.warning(f"[POLLER_DB_ERROR][RoomDBID:{db_id}] Room vanished before setup commit.")
            return

        if 'cached_players_json' in setup_data:
            room.cached_players_json = setup_data['cached_players_json']
        if 'cached_total_slots' in setup_data:
            room.cached_total_slots = setup_data['cached_total_slots']
        if 'cached_full_address' in setup_data:
            room.cached_full_address = setup_data['cached_full_address']
        if 'last_api_check' in setup_data:
            room.last_api_check = setup_data['last_api_check']
        if 'tracker_id' in setup_data:
            room.tracker_id = setup_data['tracker_id']
        if 'game_checksums_json' in setup_data:
            room.game_checksums_json = setup_data['game_checksums_json']
        
        if setup_data.get('is_setup'):
            room.is_setup = True

        session.commit()
        logging.info(f"[POLLER_SETUP][RoomDBID:{db_id}] Room metadata committed to DB.")
        
        if setup_data.get('datapackage_entries_by_game'):
            logging.debug(f"[POLLER_SETUP_DEBUG][RoomDBID:{db_id}] Saving new datapackage entries for {len(setup_data['datapackage_entries_by_game'])} game(s)...")
            for game, entries in setup_data['datapackage_entries_by_game'].items():
                try:
                    session.bulk_save_objects(entries)
                    session.commit()
                    logging.debug(f"[POLLER_SETUP_DEBUG][RoomDBID:{db_id}] Saved {len(entries)} entries for game '{game}'.")
                except IntegrityError:
                    session.rollback() 
                    logging.warning(f"[POLLER_SETUP_WARN][RoomDBID:{db_id}] Datapackage race condition for game '{game}'. Another poller saved it first. Safe to ignore.")
                except Exception as e:
                    session.rollback()
                    logging.error(f"[POLLER_SETUP_ERROR][RoomDBID:{db_id}] Error saving datapackage for game '{game}': {e}")
    
    except OperationalError as oe: 
        logging.error(f"[POLLER_ERROR][RoomDBID:{db_id}] Database was locked during setup commit. Error: {oe}")
        session.rollback()
    except Exception as e:
        logging.error(f"[POLLER_ERROR][RoomDBID:{db_id}] An unhandled exception occurred in db_commit_setup_data!", exc_info=True)
        session.rollback()
    finally:
        Session.remove()


async def poll_room_with_interval(room_info, loop):
    """
    Wrapper that calls the lightweight polling logic at a regular interval.
    """
    while True:
        try:
            await run_room_poll(room_info, loop)
        except asyncio.CancelledError:
            break
        except Exception as e:
            db_id = room_info.get('db_id', 'Unknown')
            logging.error(f"[POLLER_ERROR][RoomDBID:{db_id}] Unhandled error in poll_room_with_interval: {e}", exc_info=True)
        
        try:
            await asyncio.sleep(POLLING_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            break

async def setup_worker(setup_queue, setup_semaphore, loop):
    """A worker that processes the room setup queue one by one."""
    while True:
        try:
            room_info = await setup_queue.get()
            
            async with setup_semaphore:
                logging.info(f"[SETUP_WORKER] Starting setup for room {room_info['db_id']}")
                await run_room_setup(room_info, loop)
                logging.info(f"[SETUP_WORKER] Finished setup for room {room_info['db_id']}")
                
            setup_queue.task_done()
        except Exception as e:
            logging.error(f"[SETUP_WORKER_ERROR] Unhandled error: {e}", exc_info=True)

async def poller_supervisor(app, loop):
    """
    The main supervisor loop for the background poller.
    - Manages which rooms are actively being polled.
    - Queues new rooms for a throttled setup process.
    - Starts/stops polling tasks based on room status.
    """
    logging.info("[POLLER] Background polling service starting...")
    running_tasks = {}
    last_cleanup_time = datetime.utcnow()

    setup_queue = asyncio.Queue()
    setup_semaphore = asyncio.Semaphore(2) 
    
    logging.info(f"[SUPERVISOR] Starting 2 setup workers...")
    asyncio.create_task(setup_worker(setup_queue, setup_semaphore, loop))
    asyncio.create_task(setup_worker(setup_queue, setup_semaphore, loop))
    
    while True:
        try:
            log_resource_usage(app)

            active_rooms_in_db = await loop.run_in_executor(None, db_get_active_rooms)
            if active_rooms_in_db is None:
                logging.error("[SUPERVISOR_ERROR] Failed to fetch active rooms. Retrying...")
                await asyncio.sleep(SUPERVISOR_INTERVAL_SECONDS)
                continue
                
            current_active_room_ids = {room.id for room in active_rooms_in_db}
            
            for room in active_rooms_in_db:
                room_info = {'db_id': room.id, 'hostname': room.hostname, 'room_uuid': room.room_id}
                
                if room.id not in running_tasks:
                    if not room.is_setup:
                        logging.info(f"[SUPERVISOR] Queuing new room {room.id} ({room.room_id}) for setup.")
                        await setup_queue.put(room_info)
                    else:
                        logging.info(f"[SUPERVISOR] Starting poller for already-setup room {room.id} ({room.room_id})")
                        task = asyncio.create_task(poll_room_with_interval(room_info, loop)) # <-- Pass loop
                        running_tasks[room.id] = task

            inactive_room_ids = set(running_tasks.keys()) - current_active_room_ids
            for room_id in inactive_room_ids:
                logging.info(f"[SUPERVISOR] Room ID {room_id} is no longer active. Stopping poller.")
                task_to_stop = running_tasks.pop(room_id, None)
                if task_to_stop:
                    task_to_stop.cancel()

            if datetime.utcnow() - last_cleanup_time > timedelta(hours=24):
                logging.info("[JANITOR] Running daily cleanup of old, un-subscribed rooms...")
                await loop.run_in_executor(None, db_run_cleanup)
                last_cleanup_time = datetime.utcnow()

        except Exception as e:
            logging.error(f"[SUPERVISOR] An unhandled error occurred: {e}", exc_info=True)
        finally:
            pass

        await asyncio.sleep(SUPERVISOR_INTERVAL_SECONDS)

def db_get_active_rooms():
    """Synchronously queries for all rooms that should be active."""
    session = Session()
    try:
        return session.query(TrackedRoom).filter(
            TrackedRoom.is_complete == False,
            TrackedRoom.is_suspended == False
        ).all()
    except Exception as e:
        logging.error(f"[SUPERVISOR_DB_ERROR] Failed to get active rooms: {e}", exc_info=True)
        session.rollback()
        return None
    finally:
        Session.remove()

def db_run_cleanup():
    """Synchronously runs the daily cleanup logic."""
    session = Session()
    try:
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        rooms_to_delete = session.query(TrackedRoom).filter(
            TrackedRoom.subscriptions.any() == False,
            or_(
                TrackedRoom.last_successful_poll == None,
                TrackedRoom.last_successful_poll < thirty_days_ago
            )
        ).all()

        if rooms_to_delete:
            for room in rooms_to_delete:
                logging.info(f"[JANITOR] Deleting abandoned room {room.room_id}")
                session.delete(room)
            session.commit()
        else:
            logging.info("[JANITOR] No abandoned rooms to delete.")
    except Exception as e:
        logging.error(f"[JANITOR_DB_ERROR] Failed to run cleanup: {e}", exc_info=True)
        session.rollback()
    finally:
        Session.remove()

def run_poller(app):
    """The entry point for the poller thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    main_task = loop.create_task(poller_supervisor(app, loop))
    
    try:
        loop.run_until_complete(main_task)
    except Exception as e:
        logging.critical(f"[POLLER_CRITICAL] asyncio.run() failed: {e}", exc_info=True)
    finally:
        logging.info("[POLLER] Poller is shutting down. Cleaning up session.")
        loop.run_until_complete(close_aiohttp_session())
        loop.close()
        logging.info("[POLLER] Shutdown complete.")