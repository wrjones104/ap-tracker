import asyncio
import logging
import aiohttp
import json
import os
import random
import fnmatch
import time
import re
from dotenv import load_dotenv
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
from threading import local
from sqlalchemy import or_, exc, tuple_, func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import OperationalError, IntegrityError
from email.utils import parsedate_to_datetime

from . import Session, get_firebase_app, process
from .models import (
    User, Device, TrackedRoom, UserRoomSubscription, UserTrackedSlot,
    DatapackageCache, NotifiedItem, NotifiedHint, SlotItemThreshold
)
from .utils import get_user_agent_string, get_cheese_headers, extract_ap_room_id, fetch_json_with_status, db_suspend_room, is_snoozed, SSRFProtectedTCPConnector

from . import POLLING_INTERVAL_SECONDS, SUPERVISOR_INTERVAL_SECONDS

thread_local_data = local()
load_dotenv()

# Limit concurrent requests to Cheese Tracker API to avoid rate limits
CHEESE_POLL_SEMAPHORE_LIMIT = 3
cheese_semaphore = asyncio.Semaphore(CHEESE_POLL_SEMAPHORE_LIMIT)

# Limit concurrent requests to Archipelago API
AP_POLL_SEMAPHORE_LIMIT = 5 
ap_poll_semaphore = asyncio.Semaphore(AP_POLL_SEMAPHORE_LIMIT)

SEMAPHORE_WAIT_WARNING_THRESHOLD = 60


# =============================================================================
# CORE HELPERS & SETUP
# =============================================================================

def get_app_version():
    try:
        gradle_path = os.path.join(os.path.dirname(__file__), '../../android/app/build.gradle.kts')
        if os.path.exists(gradle_path):
            with open(gradle_path, 'r') as f:
                content = f.read()
                match = re.search(r'versionName\s*=\s*"([^"]+)"', content)
                if match:
                    return match.group(1)
    except Exception as e:
        logging.warning(f"[VERSION] Could not read version from gradle: {e}")
    return "1.0.0"

async def close_aiohttp_session():
    session = getattr(thread_local_data, "aiohttp_session", None)
    if session:
        await session.close()
        logging.info("[POLLER] Aiohttp session closed.")
    if hasattr(thread_local_data, "aiohttp_session"):
        del thread_local_data.aiohttp_session

def get_aiohttp_session():
    if not hasattr(thread_local_data, "aiohttp_session") or thread_local_data.aiohttp_session.closed:
        
        headers = {
            "User-Agent": get_user_agent_string()
        }

        thread_local_data.aiohttp_session = aiohttp.ClientSession(
            connector=SSRFProtectedTCPConnector(),
            headers=headers, 
            cookie_jar=aiohttp.DummyCookieJar()
        )
    return thread_local_data.aiohttp_session

def log_resource_usage(app):
    """Logs the current CPU and Memory usage of this script."""
    if not app.config.get('DEBUG'): return
    cpu_usage = process.cpu_percent(interval=None)
    memory_info = process.memory_info()
    memory_mb = memory_info.rss / (1024 * 1024)
    logging.debug(f"[RESOURCES] CPU: {cpu_usage:.2f}% | Memory: {memory_mb:.2f} MB")

def _extract_ap_room_id(url_string):
    if not url_string: return None
    try:
        parsed = urlparse(url_string)
        parts = parsed.path.strip('/').split('/')
        if len(parts) >= 2 and parts[0] == 'room':
            return parts[1]
    except Exception:
        pass
    return None

async def _attempt_room_wake(hostname, room_uuid):
    """
    Attempts to 'wake' a sleeping AP room by sending an HTTP GET to its public page.
    """
    url = f"https://{hostname}/room/{room_uuid}"
    logging.info(f"[POLLER_WAKE] Attempting to wake room: {url}")
    session = get_aiohttp_session()
    try:
        async with session.get(url, timeout=10) as response:
            logging.info(f"[POLLER_WAKE] Wake request sent. Status: {response.status}")
            return True
    except Exception as e:
        logging.warning(f"[POLLER_WAKE] Failed to send wake request: {e}")
        return False

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
            
        # We check if the 'bundled_items' key exists (created by our bundling logic)
        # FCM 'data' fields must be strings, so we ensure it's passed correctly.
        data_payload = {}
        if 'bundled_items' in content:
            data_payload['bundled_items'] = content['bundled_items']

        for token in device_tokens:
            android_config = messaging.AndroidConfig(priority='high')
            
            messages.append(messaging.Message(
                notification=messaging.Notification(title=content['title'], body=content['body']),
                token=token,
                android=android_config,
                data=data_payload if data_payload else None
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

async def fetch_json(url, headers=None):
    session = get_aiohttp_session()
    try:
        async with session.get(url, timeout=15) as response:
            if response.status == 429:
                retry_after = response.headers.get("Retry-After", "unknown")
                logging.warning(f"[HTTP_429] Rate limited on {url}. Retry-After: {retry_after}")
                return None
            
            response.raise_for_status()
            return await response.json()
    except Exception as e:
        logging.warning(f"[HTTP_ERROR] Failed to fetch {url}: {e}")
        return None

# =============================================================================
# POLL LOGIC & SUBROUTINES
# =============================================================================

def _check_player_completion(tracker_data, players_list, room_db_id, users_by_id, prefs_by_user_slot, tracked_slots_by_user, backfill_check_set, full_name_map, short_name_map, aliases_by_user):
    """
    Checks both AP status AND location counts to determine if players are finished.
    Returns: (notifications_dict, finished_player_ids_set, players_list_updated_bool)
    """
    notifications_by_user = {}
    final_finished_ids = set()

    # 1. Parse Status from 'player_status' (Network Truth)
    network_finished_ids = set()
    player_statuses_raw = tracker_data.get('player_status', {})
    if isinstance(player_statuses_raw, dict): 
        network_finished_ids.update({int(p) for p, s in player_statuses_raw.items() if s == 30})
    elif isinstance(player_statuses_raw, list):
            for status_info in player_statuses_raw:
                if isinstance(status_info, dict) and status_info.get('status') == 30 and 'player' in status_info:
                    network_finished_ids.add(status_info.get('player'))

    # 2. Update Cache & Build Final Truth
    players_just_marked_finished = set()
    players_list_updated = False
    
    has_status_data = len(tracker_data.get('player_status', {})) > 0

    for player in players_list:
        slot_id = player.get('slot_id')
        is_actually_finished = slot_id in network_finished_ids
        was_marked_finished = player.get('is_finished', False)
    
        if is_actually_finished and not was_marked_finished:
            # Case A: They just finished (Status 30)
            player['is_finished'] = True
            players_list_updated = True
            players_just_marked_finished.add(slot_id)
            final_finished_ids.add(slot_id) 
            
        elif not is_actually_finished and was_marked_finished and has_status_data:
            # Case B: False Positive (Revert)
            player['is_finished'] = False
            players_list_updated = True
            logging.info(f"[POLLER_FIX][RoomDBID:{room_db_id}] Reverting 'Finished' status for Slot {slot_id}.")
            # Do NOT add to final_finished_ids
            
        else:
            # Case C: Status Unchanged
            if player.get('is_finished', False):
                final_finished_ids.add(slot_id)

    if players_list_updated:
        logging.info(f"[POLLER_ACTION][RoomDBID:{room_db_id}] {len(players_just_marked_finished)} player(s) just finished.")

    # 3. Generate Notifications
    if players_just_marked_finished:
        finished_players_by_user = {} 
        for user_id, tracked_slots in tracked_slots_by_user.items():
            for slot_id in players_just_marked_finished:
                if slot_id in tracked_slots:
                    finished_players_by_user.setdefault(user_id, []).append(slot_id)

        for user_id, finished_slot_ids in finished_players_by_user.items():
            user_prefs = users_by_id.get(user_id)
            if not user_prefs: continue 

            names_to_notify = [] 
            
            use_condensed = user_prefs.use_condensed_messages_default
            remove_emojis = user_prefs.remove_emojis_default
            first_slot_id = finished_slot_ids[0]
            first_slot_prefs = prefs_by_user_slot.get(user_id, {}).get(first_slot_id)
            if first_slot_prefs:
                if first_slot_prefs.use_condensed_messages is not None:
                    use_condensed = first_slot_prefs.use_condensed_messages
                if first_slot_prefs.remove_emojis is not None:
                    remove_emojis = first_slot_prefs.remove_emojis

            current_name_map = short_name_map if use_condensed else full_name_map

            for slot_id in finished_slot_ids:
                slot_prefs = prefs_by_user_slot.get(user_id, {}).get(slot_id)
                if not slot_prefs: continue 

                if (user_id, slot_id) in backfill_check_set:
                    logging.debug(f"[NOTIFY_SKIP][RoomDBID:{room_db_id}] User {user_id} tracking Slot {slot_id} is backfilling. Suppressing 'Finished' notification.")
                    continue 
                
                notify_override = slot_prefs.notify_finished
                should_notify = notify_override if notify_override is not None else user_prefs.notify_finished_default
                
                if should_notify:
                    player_name = current_name_map.get(slot_id, f"Player {slot_id}")
                    names_to_notify.append(player_name)
                else:
                    logging.info(f"[NOTIFY_SKIP] User {user_id} has disabled finished notifications for Slot {slot_id}.")

            if not names_to_notify:
                continue

            player_names_str = ", ".join(names_to_notify)
            alias = aliases_by_user.get(user_id, "Unknown Room")
            icon = "" if remove_emojis else "🏁 "
            
            notifications_by_user.setdefault(user_id, []).append({
                'title': f"{icon}Player(s) Finished!",
                'body': f"{player_names_str} has finished in '{alias}'!",
                'type': 'player_finish',
                'details': (room_db_id, user_id, player_names_str)
            })
            
    return notifications_by_user, final_finished_ids, players_list_updated

def _process_received_items(tracker_data, room_uuid, room_db_id, existing_items_in_db, tracked_slots_by_user, game_map, game_checksums, has_item_history):
    """
    Iterates player_items_received, dedupes against DB, creates objects, and preps notifications.
    """
    items_to_add = []
    new_items_for_notify = []
    cache_keys_to_fetch = set()
    items_in_this_batch = set()
    
    items_processed_count = 0
    items_skipped_classification = 0
    items_skipped_duplicate = 0
    items_added_count = 0
    items_skipped_backfill = 0
    added_items_details = []

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
                item_id, loc_id, send_id = int(item_id), int(loc_id), int(send_id)
            except (ValueError, TypeError, IndexError) as e:
                continue 

            item_key_db = (rid, item_id, loc_id)
            item_key_batch = (room_uuid, rid, item_id, loc_id) 

            if (item_key_db in existing_items_in_db) or (item_key_batch in items_in_this_batch):
                items_skipped_duplicate += 1
                continue

            if not (flags & 1 or flags & 2):
                items_skipped_classification += 1
                continue

            items_to_add.append(NotifiedItem(
                room_id=room_uuid,
                receiving_slot_id=rid,
                sending_slot_id=send_id,
                item_id=item_id,
                location_id=loc_id,
                item_flags=flags,
                timestamp=datetime.now(timezone.utc)
            ))
            items_in_this_batch.add(item_key_batch)
            items_added_count += 1
            added_items_details.append(f"(Slot:{rid}, Item:{item_id}, Loc:{loc_id})")

            if has_item_history: 
                receiver_game = game_map.get(rid, "Unknown")
                game_checksum = game_checksums.get(receiver_game)
                if game_checksum:
                    cache_keys_to_fetch.add((game_checksum, 'item', item_id))

                sender_game = game_map.get(send_id, "Unknown")
                sender_checksum = game_checksums.get(sender_game)
                if sender_checksum:
                    cache_keys_to_fetch.add((sender_checksum, 'location', loc_id))
                
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
        added_str = ", ".join(added_items_details) if added_items_details else "None"
        logging.debug(f"[POLLER_DEBUG][RoomDBID:{room_db_id}] Items: Proc={items_processed_count}, SkipClass={items_skipped_classification}, SkipDupe={items_skipped_duplicate}, Added={items_added_count}")
    
    if items_skipped_backfill > 0:
        logging.info(f"[POLLER_INFO][RoomDBID:{room_db_id}] Suppressed {items_skipped_backfill} item notifications (backfill).")

    return items_to_add, new_items_for_notify, cache_keys_to_fetch, items_added_count

def _process_hints(tracker_data, room_uuid, room_db_id, existing_hints_map, game_map, game_checksums, has_hint_history):
    """
    Iterates hints, dedupes, creates objects, detects found hints, preps notifications.
    NOW: Filters by Item Flags (Progression/Useful only).
    """
    hints_to_add = []
    new_hints_for_notify = []
    cache_keys_to_fetch = set()
    just_found_hint_item_loc_pairs = set()
    hints_in_this_batch = set()

    hints_processed_count = 0
    hints_added_count = 0
    hints_skipped_backfill = 0
    hints_skipped_classification = 0

    for p_hints in tracker_data.get('hints', []):
         for hint_data in p_hints.get('hints', []):
            hints_processed_count += 1
            try:
                if len(hint_data) < 5: continue 
                
                io_id = int(hint_data[0])
                lo_id = int(hint_data[1])
                loc_id = int(hint_data[2])
                item_id = int(hint_data[3])
                is_found_from_tracker = bool(hint_data[4])
                flags = int(hint_data[6]) if len(hint_data) > 6 else 0
                
            except (ValueError, IndexError):
                continue

            if not (flags & 0b011):
                hints_skipped_classification += 1
                continue

            hint_key_db = (io_id, lo_id, item_id, loc_id)
            hint_key_batch = (room_uuid, io_id, lo_id, item_id, loc_id)

            existing_hint_obj = existing_hints_map.get(hint_key_db)

            if not existing_hint_obj:
                if hint_key_batch in hints_in_this_batch: continue
                
                hints_to_add.append(NotifiedHint(
                    room_id=room_uuid,
                    item_owner_id=io_id,
                    location_owner_id=lo_id,
                    item_id=item_id,
                    location_id=loc_id,
                    is_found=is_found_from_tracker,
                    timestamp=datetime.now(timezone.utc),
                    item_flags=flags
                ))
                hints_in_this_batch.add(hint_key_batch)
                hints_added_count += 1

                if has_hint_history:
                    io_game = game_map.get(io_id, "Unknown")
                    lo_game = game_map.get(lo_id, "Unknown")
                    io_checksum = game_checksums.get(io_game)
                    lo_checksum = game_checksums.get(lo_game)

                    if io_checksum:
                        cache_keys_to_fetch.add((io_checksum, 'item', item_id))
                    if lo_checksum:
                        cache_keys_to_fetch.add((lo_checksum, 'location', loc_id))
                    
                    new_hints_for_notify.append({
                        'hint_key_batch': hint_key_batch,
                        'io_id': io_id, 'lo_id': lo_id, 'item_id': item_id, 'loc_id': loc_id,
                        'io_game': io_game, 'lo_game': lo_game,
                        'io_checksum': io_checksum, 'lo_checksum': lo_checksum,
                        'flags': flags
                    })
                    
                    if is_found_from_tracker:
                        just_found_hint_item_loc_pairs.add((loc_id, item_id))
                else:
                    hints_skipped_backfill += 1
            
            else:
                if is_found_from_tracker and not existing_hint_obj.is_found:
                    existing_hint_obj.is_found = True                     
                    existing_hint_obj.timestamp = datetime.now(timezone.utc)                    
                    just_found_hint_item_loc_pairs.add((loc_id, item_id))                    
                    logging.debug(f"[POLLER_HINT_UPDATE] Marked hint {item_id} as found. Bumped timestamp.")
    
    if hints_processed_count > 0:
         logging.debug(f"[POLLER_DEBUG][RoomDBID:{room_db_id}] Hints: Proc={hints_processed_count}, SkipClass={hints_skipped_classification}, Added={hints_added_count}")
    if hints_skipped_backfill > 0:
        logging.info(f"[POLLER_INFO][RoomDBID:{room_db_id}] Suppressed {hints_skipped_backfill} hint notifications (backfill).")

    return hints_to_add, new_hints_for_notify, cache_keys_to_fetch, just_found_hint_item_loc_pairs

def _resolve_names_and_notify(session, room_db_id, cache_keys_to_fetch, new_items_for_notify, new_hints_for_notify, users_by_id, prefs_by_user_slot, tracked_slots_by_user, aliases_by_user, full_name_map, short_name_map, backfill_check_set, just_found_hint_item_loc_pairs, finished_player_ids, connected_slots_set):  
    """
    Fetches names from DB in chunks and constructs final notification payloads.
    Applies filtering, backfill checks, ignore lists, alias/condensed formatting, and snooze logic.
    """
    notifications_by_user = {}
    name_lookup_map = {}
    
    # We capture the current time once at the start of the batch for consistent comparison
    now_utc = datetime.now(timezone.utc)

    # 0. Pre-fetch Thresholds for all slots in this batch
    thresholds_lookup = {}
    all_db_slot_ids = []
    for user_slots in prefs_by_user_slot.values():
        for slot_obj in user_slots.values():
            all_db_slot_ids.append(slot_obj.id)
    
    if all_db_slot_ids:
        try:
            thresholds = session.query(SlotItemThreshold).filter(SlotItemThreshold.user_tracked_slot_id.in_(all_db_slot_ids)).all()
            for t in thresholds:
                key = (t.user_tracked_slot_id, t.item_name.lower().strip())
                if key not in thresholds_lookup:
                    thresholds_lookup[key] = set()
                thresholds_lookup[key].add(t.threshold)
        except Exception as e:
            logging.error(f"[POLLER_THRESHOLD_ERROR] Failed to fetch thresholds: {e}")

    # 1. Fetch Names from DatapackageCache
    if cache_keys_to_fetch:
        logging.debug(f"[POLLER_DEBUG][RoomDBID:{room_db_id}] Fetching {len(cache_keys_to_fetch)} names...")
        try:
            ids_to_fetch = {k[2] for k in cache_keys_to_fetch}
            checksums_to_fetch = {k[0] for k in cache_keys_to_fetch}
            
            ids_list = list(ids_to_fetch)
            chunk_size = 1000
            
            for i in range(0, len(ids_list), chunk_size):
                id_chunk = ids_list[i:i + chunk_size]
                
                results = session.query(
                    DatapackageCache.checksum,
                    DatapackageCache.entity_type, DatapackageCache.entity_id,
                    DatapackageCache.entity_name
                ).filter(
                    DatapackageCache.checksum.in_(checksums_to_fetch),
                    DatapackageCache.entity_id.in_(id_chunk)
                ).all()

                for chk, etype, eid, name in results:
                    key = (chk, etype, eid)
                    if key in cache_keys_to_fetch:
                        name_lookup_map[key] = name

        except Exception as e:
            logging.error(f"[POLLER_DB_ERROR][RoomDBID:{room_db_id}] Failed to bulk-fetch names: {e}", exc_info=True)
            return {}

    # 2. Notify Items
    batch_threshold_counts = {} # (slot_db_id, item_name) -> current_batch_count

    # Optimization: Pre-fetch DB counts for all relevant items in this batch to avoid N+1 problem
    db_counts_lookup = {}
    if new_items_for_notify:
        count_keys = set()
        for item_data in new_items_for_notify:
            count_keys.add((
                item_data['item_key_batch'][0], # room_uuid
                item_data['receiving_slot_id'],
                item_data['item_id']
            ))
        
        if count_keys:
            try:
                # Use chunking if count_keys is very large (unlikely in poller but good practice)
                for chunk in chunked_iterable(list(count_keys), 1000):
                    counts_query = session.query(
                        NotifiedItem.room_id, 
                        NotifiedItem.receiving_slot_id, 
                        NotifiedItem.item_id, 
                        func.count(NotifiedItem.id)
                    ).filter(
                        tuple_(NotifiedItem.room_id, NotifiedItem.receiving_slot_id, NotifiedItem.item_id).in_(chunk)
                    ).group_by(
                        NotifiedItem.room_id, NotifiedItem.receiving_slot_id, NotifiedItem.item_id
                    ).all()
                    
                    for r, s, i, c in counts_query:
                        db_counts_lookup[(r, s, i)] = c
            except Exception as e:
                logging.error(f"[POLLER_THRESHOLD_COUNT_ERROR] Failed to bulk-fetch item counts: {e}")

    for item_data in new_items_for_notify:
        item_name = name_lookup_map.get(
            (item_data['game_checksum'], 'item', item_data['item_id']),
            f"ID {item_data['item_id']}"
        )
        loc_name = name_lookup_map.get(
            (item_data['sender_checksum'], 'location', item_data['location_id']),
            f"ID {item_data['location_id']}"
        )
        
        item_id = item_data['item_id']
        loc_id = item_data['location_id']
        rid = item_data['receiving_slot_id']
        send_id = item_data['sending_slot_id']
        is_a_found_hint = (loc_id, item_id) in just_found_hint_item_loc_pairs

        for user_id, tracked_slots in tracked_slots_by_user.items():
            if rid in tracked_slots:
                # 1. Load User/Slot Preferences
                user_prefs = users_by_id.get(user_id)
                slot_prefs = prefs_by_user_slot.get(user_id, {}).get(rid)
                
                if not user_prefs or not slot_prefs: continue

                if is_snoozed(user_prefs, slot_prefs, now_utc, user_id, rid, "item"):
                    continue

                # Helper to resolve overrides
                def get_pref(attr, default_attr):
                    val = getattr(user_prefs, default_attr)
                    if slot_prefs and getattr(slot_prefs, attr) is not None:
                        val = getattr(slot_prefs, attr)
                    return val

                suppress_own = get_pref('suppress_own_events', 'suppress_own_events_default')
                suppress_self = get_pref('suppress_self_found', 'suppress_self_found_default')
                should_suppress_connected = get_pref('suppress_connected', 'suppress_connected_default')
                
                if should_suppress_connected and (rid in connected_slots_set):
                    logging.debug(f"[NOTIFY_SUPPRESSED] User {user_id}: Slot {rid} is connected.")
                    continue
                
                remove_emojis = get_pref('remove_emojis', 'remove_emojis_default')

                # 2. Suppression Logic
                is_from_self = (rid == send_id)
                
                if is_from_self:
                    if suppress_self:
                        logging.debug(f"[NOTIFY_SUPPRESSED] User {user_id}: Self-found item (Slot {rid}).")
                        continue
                elif send_id in tracked_slots:
                    if suppress_own:
                        logging.debug(f"[NOTIFY_SUPPRESSED] User {user_id}: Cross-slot item (From {send_id} to {rid}).")
                        continue
                
                # Resolving Aliases for Display and Context
                # 'alias' is the User's custom name for this Room
                room_alias = aliases_by_user.get(user_id, "Unknown Room")

                # 'receiver_alias' is the User's custom name for this specific SLOT (if set), or fall back to full name
                receiver_alias = short_name_map.get(rid, f"Slot {rid}")
                # 'receiver_original' is the actual player name from the server
                receiver_original = full_name_map.get(rid, f"Slot {rid}")


                # Check Finished Suppression
                wants_finished_notifs = slot_prefs.notify_finished if slot_prefs.notify_finished is not None else user_prefs.notify_finished_default
                if rid in finished_player_ids and not wants_finished_notifs:
                    logging.info(f"[NOTIFY_SUPPRESSED] User {user_id} suppressed item for Slot {rid} (Slot Finished).")
                    continue

                # Check Backfill Suppression
                if (user_id, rid) in backfill_check_set:
                    logging.debug(f"[NOTIFY_SKIP][RoomDBID:{room_db_id}] User {user_id} tracking Slot {rid} is backfilling. Suppressing item {item_data['item_id']}.")
                    continue

                # --- IGNORE LIST CHECK ---
                normalized_item_name = item_name.lower().strip()
                should_ignore = False

                # --- THRESHOLD CHECK ---
                is_threshold_hit = False
                current_total_count = 0
                threshold = thresholds_lookup.get((slot_prefs.id, normalized_item_name))
                if threshold:
                    # Increment count for this batch
                    batch_key = (slot_prefs.id, normalized_item_name)
                    batch_threshold_counts[batch_key] = batch_threshold_counts.get(batch_key, 0) + 1
                    
                    try:
                        db_count_key = (item_data['item_key_batch'][0], rid, item_id)
                        db_count = db_counts_lookup.get(db_count_key, 0)
                        
                        current_total_count = db_count + batch_threshold_counts[batch_key]
                        
                        logging.debug(f"[THRESHOLD_DEBUG] User {user_id} Slot {rid} checking '{normalized_item_name}': DB={db_count}, Batch={batch_threshold_counts[batch_key]}, Total={current_total_count}, Thresholds={threshold}")

                        if current_total_count not in threshold:
                            logging.debug(f"[THRESHOLD_SKIP] User {user_id}: Slot {rid} hit milestone {current_total_count} (Not in {threshold}) for '{item_name}'. Skipping.")
                            continue
                        else:
                            is_threshold_hit = True
                            logging.info(f"[THRESHOLD_HIT] User {user_id}: Slot {rid} reached threshold milestone {current_total_count} for '{item_name}'. Notifying!")
                    except Exception as e:
                        logging.error(f"[POLLER_THRESHOLD_COUNT_ERROR] Failed to count items: {e}")
                else:
                    # Log if we find no threshold for an item that we might expect one for (optional, very noisy)
                    # logging.debug(f"[THRESHOLD_NONE] No threshold for {(slot_prefs.id, normalized_item_name)}")
                    pass
                
                if user_prefs.ignore_items:
                    for ignore_rule in user_prefs.ignore_items:
                        rule_pattern = ignore_rule.item_name.lower().strip()
                        if fnmatch.fnmatch(normalized_item_name, rule_pattern):
                            if not ignore_rule.game_name:
                                should_ignore = True
                                break
                            elif ignore_rule.game_name.lower().strip() == item_data['receiver_game'].lower().strip():
                                should_ignore = True
                                break
                
                if should_ignore and not is_threshold_hit:
                    logging.info(f"[NOTIFY_SUPPRESSED] User {user_id} ignored item '{item_name}' (matched rule '{rule_pattern}') for game '{item_data['receiver_game']}'.")
                    continue

                # --- CONDENSED MESSAGING CHECK ---
                use_condensed = user_prefs.use_condensed_messages_default
                if slot_prefs.use_condensed_messages is not None:
                    use_condensed = slot_prefs.use_condensed_messages

                current_name_map = short_name_map if use_condensed else full_name_map
                sender_name = current_name_map.get(send_id, f'P{send_id}')
                receiver_name = current_name_map.get(rid, f'P{rid}')

                # Build Body
                if use_condensed:
                    body = f"Sent to {receiver_name} by {sender_name}"
                else:
                    body = f"{sender_name} sent {item_name} to {receiver_name} ({loc_name})"

                is_progression = bool(item_data['flags'] & 1)
                should_notify = False
                title_prefix = ""
                item_type = ""
                
                # Icons
                icon_prog = "" if remove_emojis else "🏆 "
                icon_useful = "" if remove_emojis else "✅ "
                icon_milestone = "" if remove_emojis else "🚩 "
                icon_bulb = "" if remove_emojis else "💡 "
                
                if is_threshold_hit:
                    title_prefix = f"{icon_milestone}Milestone! {item_name} ({current_total_count})"
                    item_type = "item_milestone"
                    should_notify = True # Threshold hits always notify
                elif is_progression:
                    title_prefix = f"{icon_prog}{item_name}"
                    item_type = "item_progression"
                    notify_override = slot_prefs.notify_progression
                    should_notify = notify_override if notify_override is not None else user_prefs.notify_progression_default
                else:
                    title_prefix = f"{icon_useful}{item_name}"
                    item_type = "item_useful"
                    notify_override = slot_prefs.notify_useful
                    should_notify = notify_override if notify_override is not None else user_prefs.notify_useful_default
                
                if is_a_found_hint:
                    title_prefix = icon_bulb + title_prefix
                
                title = f"{title_prefix} - [{room_alias}]"
                
                if should_notify:
                    notifications_by_user.setdefault(user_id, []).append({
                        'title': title, 
                        'body': body, 
                        'type': item_type, 
                        'details': item_data['item_key_batch'],
                        
                        # --- Context for clean bundle formatting ---
                        'item_context': {
                            'item_name': item_name,
                            'alias': receiver_alias,
                            'original': receiver_original
                        }
                    })

    # 3. Notify Hints
    for hint_data in new_hints_for_notify:
        item_name = name_lookup_map.get(
            (hint_data['io_checksum'], 'item', hint_data['item_id']),
            f"ID {hint_data['item_id']}"
        )
        loc_name = name_lookup_map.get(
            (hint_data['lo_checksum'], 'location', hint_data['loc_id']),
            f"ID {hint_data['loc_id']}"
        )
        io_id, lo_id = hint_data['io_id'], hint_data['lo_id']

        for user_id, tracked_slots in tracked_slots_by_user.items():
            is_for_us = io_id in tracked_slots
            is_at_our_location = lo_id in tracked_slots

            if is_for_us or is_at_our_location:
                
                if io_id == lo_id:
                    logging.debug(f"[POLLER_DEBUG] Skipped Hint {hint_data['item_id']} for User {user_id}: Self-hint.")
                    continue

                user_prefs = users_by_id.get(user_id)
                if not user_prefs: continue
                
                relevant_slot = io_id if is_for_us else lo_id
                relevant_slot_prefs = prefs_by_user_slot.get(user_id, {}).get(relevant_slot)

                if is_snoozed(user_prefs, relevant_slot_prefs, now_utc, user_id, relevant_slot, "hint"):
                    continue

                # Check Finished
                wants_finished_notifs = user_prefs.notify_finished_default
                if relevant_slot_prefs and relevant_slot_prefs.notify_finished is not None:
                    wants_finished_notifs = relevant_slot_prefs.notify_finished

                if relevant_slot in finished_player_ids and not wants_finished_notifs:
                    logging.info(f"[NOTIFY_SUPPRESSED] User {user_id} suppressed hint for Slot {relevant_slot} (Slot Finished).")
                    continue
                
                # Check Notification Rules
                should_send_notification = False

                # Rule 1: Hints for MY Items
                if is_for_us:
                    wants_remote = getattr(user_prefs, 'notify_hints_remote_items_default', True)
                    if relevant_slot_prefs and relevant_slot_prefs.notify_hints_remote_items is not None:
                        wants_remote = relevant_slot_prefs.notify_hints_remote_items
                    if wants_remote:
                        should_send_notification = True

                # Rule 2: Hints for Items in MY World
                if is_at_our_location and not should_send_notification:
                    wants_local = user_prefs.notify_hints_default
                    if relevant_slot_prefs and relevant_slot_prefs.notify_hints is not None:
                          wants_local = relevant_slot_prefs.notify_hints
                    if wants_local:
                        should_send_notification = True
                
                if not should_send_notification:
                    continue

                # Check Backfill
                relevant_slot_for_backfill = io_id if (is_for_us and should_send_notification) else lo_id
                if (user_id, relevant_slot_for_backfill) in backfill_check_set:
                    continue

                # Check Emoji Pref
                remove_emojis = user_prefs.remove_emojis_default
                if relevant_slot_prefs and relevant_slot_prefs.remove_emojis is not None:
                    remove_emojis = relevant_slot_prefs.remove_emojis

                # Condensed Check
                use_condensed = user_prefs.use_condensed_messages_default
                if relevant_slot_prefs and relevant_slot_prefs.use_condensed_messages is not None:
                    use_condensed = relevant_slot_prefs.use_condensed_messages

                current_name_map = short_name_map if use_condensed else full_name_map
                
                # --- BUILD NOTIFICATION ---
                room_alias = aliases_by_user.get(user_id, "Unknown Room")
                
                icon_bulb = "" if remove_emojis else "💡 "
                hint_sub_icon = ""
                if not remove_emojis:
                    hint_sub_icon = "🏆" if (hint_data.get('flags', 0) & 1) else "✅"
                
                if hint_sub_icon:
                      title = f"{icon_bulb}{hint_sub_icon} New Hint! - {item_name} - [{room_alias}]"
                else:
                      title = f"{icon_bulb}New Hint! - {item_name} - [{room_alias}]"
                
                item_owner_name = current_name_map.get(io_id, f'P{io_id}')
                location_owner_name = current_name_map.get(lo_id, f'P{lo_id}')
                
                body = f"{item_owner_name}'s {item_name} is at {loc_name} in {location_owner_name}'s World"
                
                notifications_by_user.setdefault(user_id, []).append({
                    'title': title, 'body': body, 'type': 'hint', 'details': hint_data['hint_key_batch']
                })
    
    return notifications_by_user


def db_process_poll_data(db_id, room_uuid, tracker_data, room_data, remote_activity_ts=None, updated_address=None, connected_slots=None):
    """
    Synchronously processes tracker data and updates the database.
    """
    connected_slots_set = set(connected_slots) if connected_slots else set()
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=db_id).first()
        if not room: 
            logging.warning(f"[POLLER_DB_ERROR][RoomDBID:{db_id}] Room vanished before poll processing.")
            return

        if not tracker_data:
            room.failed_poll_count += 1
            if room.failed_poll_count >= 60: room.is_suspended = True
            session.commit()
            return

        room.failed_poll_count = 0
        room.last_successful_poll = datetime.utcnow()

        if remote_activity_ts:
            room.last_remote_activity = remote_activity_ts

        if updated_address:
            # Only log if it's actually different to avoid noise
            if room.cached_full_address != updated_address:
                logging.info(f"[POLLER_PORT] Updating address for Room {db_id}: {room.cached_full_address} -> {updated_address}")
                room.cached_full_address = updated_address
        
        cached_players_json_str = room_data['cached_players_json_str']
        game_checksums_json_str = room_data['game_checksums_json_str']
        is_complete_status = room_data['is_complete_status']
        
        # 1. Load existing player cache
        players = json.loads(cached_players_json_str if cached_players_json_str else '[]')
        game_checksums = json.loads(game_checksums_json_str if game_checksums_json_str else '{}')

        aliases_raw = tracker_data.get('aliases', [])
        alias_map = {}
        
        if isinstance(aliases_raw, list):
            for entry in aliases_raw:
                if entry.get('alias') and 'player' in entry:
                    alias_map[entry['player']] = entry['alias']

        # --- SELF-HEALING CHECK ---
        local_slot_ids = {p['slot_id'] for p in players}
        remote_alias_ids = set(alias_map.keys())
        unknown_ids = remote_alias_ids - local_slot_ids
        
        if len(unknown_ids) > 0:
            logging.warning(f"[POLLER_HEALING][RoomDBID:{db_id}] Detected {len(unknown_ids)} unknown slots in Alias Map (e.g. {list(unknown_ids)[:3]}). Local cache is stale. Forcing Re-Setup.")
            room.is_setup = False
            session.commit()
            return # Stop processing this poll cycle

        players_updated_local = False 
        
        # Update local player objects if aliases have changed
        for player in players:
            slot_id = player.get('slot_id')
            current_stored_alias = player.get('alias') 
            new_remote_alias = alias_map.get(slot_id)

            if new_remote_alias != current_stored_alias:
                player['alias'] = new_remote_alias
                players_updated_local = True
                logging.info(f"[POLLER] Detected alias change for Slot {slot_id}: {current_stored_alias} -> {new_remote_alias}")

        # --- IMMEDIATE COMMIT FOR ALIASES ---
        if players_updated_local:
            try:
                room.cached_players_json = json.dumps(players)
                session.commit()
                logging.info(f"[POLLER] Persisted alias updates for Room {db_id}.")
            except Exception as e:
                logging.error(f"[POLLER_ERROR] Failed to persist aliases: {e}")
                session.rollback()
                return

        full_name_map = {}   # Format: Alias (Original)
        short_name_map = {}  # Format: Alias (or Original if no alias)

        for p in players:
            original_name = p.get('name', f"Player {p['slot_id']}")
            alias = p.get('alias')
            
            if alias:
                full_name_map[p['slot_id']] = f"{alias} ({original_name})"
                short_name_map[p['slot_id']] = alias
            else:
                full_name_map[p['slot_id']] = original_name
                short_name_map[p['slot_id']] = original_name

        game_map = {p['slot_id']: p['game'] for p in players}

        has_item_history = session.query(NotifiedItem.id).filter_by(room_id=room_uuid).limit(1).scalar() is not None
        has_hint_history = session.query(NotifiedHint.id).filter_by(room_id=room_uuid).limit(1).scalar() is not None

        existing_items_in_db = set(session.query(NotifiedItem.receiving_slot_id, NotifiedItem.item_id, NotifiedItem.location_id).filter_by(room_id=room_uuid))
        existing_hints_map = {
            (h.item_owner_id, h.location_owner_id, h.item_id, h.location_id): h
            for h in session.query(NotifiedHint).filter_by(room_id=room_uuid)
        }

        # 1. Primary Query (Should filter archived, but we will double check)
        all_tracked_slots_in_room = session.query(UserTrackedSlot)\
            .join(UserTrackedSlot.subscription)\
            .filter(
                UserTrackedSlot.room_id == db_id,
                UserRoomSubscription.is_archived == False
            ).all()

        if not all_tracked_slots_in_room:
             session.commit()
             return

        slots_to_clear_backfill = [slot for slot in all_tracked_slots_in_room if slot.needs_backfill]
        backfill_check_set = {(slot.user_id, slot.slot_id) for slot in slots_to_clear_backfill}

        tracked_slots_by_user = {}
        prefs_by_user_slot = {}
        all_user_ids_in_room = set()
        for slot in all_tracked_slots_in_room:
            tracked_slots_by_user.setdefault(slot.user_id, set()).add(slot.slot_id)
            prefs_by_user_slot.setdefault(slot.user_id, {})[slot.slot_id] = slot
            all_user_ids_in_room.add(slot.user_id)

        users_by_id = {
            u.id: u for u in session.query(User)
            .options(selectinload(User.ignore_items))
            .filter(User.id.in_(all_user_ids_in_room))
        }
        
        # --- SAFETY CHECK: Explicitly verify Archive Status ---
        aliases_by_user = {}
        archived_users_found = set()
        
        # We fetch is_archived explicitly here to verify the User IDs we collected
        sub_check_query = session.query(
            UserRoomSubscription.user_id, 
            UserRoomSubscription.alias, 
            UserRoomSubscription.is_archived
        ).filter(
            UserRoomSubscription.user_id.in_(all_user_ids_in_room), 
            UserRoomSubscription.room_id == db_id
        ).all()
        
        for uid, alias, is_arch in sub_check_query:
            if is_arch:
                archived_users_found.add(uid)
            else:
                aliases_by_user[uid] = alias

        # If any users are actually archived (despite the initial query), remove them now.
        if archived_users_found:
            logging.info(f"[POLLER_GUARD] Pruning {len(archived_users_found)} archived users who slipped through initial query.")
            for uid in archived_users_found:
                tracked_slots_by_user.pop(uid, None)
                prefs_by_user_slot.pop(uid, None)
                users_by_id.pop(uid, None)
                backfill_check_set = {k for k in backfill_check_set if k[0] != uid}

        # --- LOGIC STEP 1: Check Player Completions ---
        finish_notifs, finished_player_ids, players_updated_finished = _check_player_completion(
            tracker_data, players, db_id, users_by_id, prefs_by_user_slot, 
            tracked_slots_by_user, backfill_check_set, full_name_map, short_name_map, aliases_by_user
        )
        
        if players_updated_finished:
             room.cached_players_json = json.dumps(players)

        total_players = len(players)
        if total_players > 0 and len(finished_player_ids) >= total_players:
            if not is_complete_status:
                room.is_complete = True
                logging.info(f"[POLLER_ACTION][RoomDBID:{db_id}] Room marked as complete.")

        # --- LOGIC STEP 2: Process Items ---
        items_to_add, new_items_notif, item_cache_keys, items_added_count = _process_received_items(
            tracker_data, room_uuid, db_id, existing_items_in_db, tracked_slots_by_user, 
            game_map, game_checksums, has_item_history
        )

        # --- LOGIC STEP 3: Process Hints ---
        hints_to_add, new_hints_notif, hint_cache_keys, just_found_hints = _process_hints(
            tracker_data, room_uuid, db_id, existing_hints_map, game_map, game_checksums, has_hint_history
        )

        # --- LOGIC STEP 4: Resolve Names & Build Notifications ---
        all_cache_keys = item_cache_keys | hint_cache_keys
        data_notifs = _resolve_names_and_notify(
            session, db_id, all_cache_keys, new_items_notif, new_hints_notif,
            users_by_id, prefs_by_user_slot, tracked_slots_by_user, aliases_by_user, 
            full_name_map, short_name_map,
            backfill_check_set, just_found_hints, finished_player_ids, connected_slots_set
        )

        # Combine notifications (Finished + Items + Hints)
        notifications_to_send = {}
        
        def merge_notifs(source, dest):
            for uid, notif_list in source.items():
                dest.setdefault(uid, []).extend(notif_list)

        merge_notifs(finish_notifs, notifications_to_send)
        merge_notifs(data_notifs, notifications_to_send)

        if items_to_add:
            session.bulk_save_objects(items_to_add)
            if not has_item_history:
                logging.debug(f"[POLLER][RoomDBID:{db_id}] Silently backfilled {len(items_to_add)} historical items.")
            elif not new_items_notif: 
                logging.debug(f"[POLLER][RoomDBID:{db_id}] Silently added {len(items_to_add)} new items (Suppressed/Untracked).")

        if hints_to_add:
            session.bulk_save_objects(hints_to_add)
            if not has_hint_history:
                logging.debug(f"[POLLER][RoomDBID:{db_id}] Silently backfilled {len(hints_to_add)} historical hints.")

        if slots_to_clear_backfill:
            logging.debug(f"[POLLER_ACTION][RoomDBID:{db_id}] Clearing 'needs_backfill' for {len(slots_to_clear_backfill)} slots.")
            for slot in slots_to_clear_backfill:
                slot.needs_backfill = False

        final_payloads = {}
        if notifications_to_send:
            devices_to_notify = session.query(Device).filter(Device.user_id.in_(notifications_to_send.keys())).all()
            tokens_by_user = {}
            for device in devices_to_notify: 
                tokens_by_user.setdefault(device.user_id, []).append(device.fcm_token)

            for user_id, raw_notifs in notifications_to_send.items():
                user_tokens = tokens_by_user.get(user_id)
                if user_tokens:
                    user_prefs = users_by_id.get(user_id)
                    
                    # Dedupe first
                    unique_notifications = list({json.dumps(d): d for d in raw_notifs}.values())
                    
                    # Compress
                    processed_notifications = compress_notifications(
                        unique_notifications, 
                        user_prefs, 
                        prefs_by_user_slot.get(user_id, {})
                    )

                    final_payloads[user_id] = {
                        'notifications': processed_notifications,
                        'tokens': user_tokens,
                        'alias': aliases_by_user.get(user_id)
                    }

        session.commit()
        return final_payloads

    except OperationalError as oe: 
        logging.error(f"[POLLER_ERROR][RoomDBID:{db_id}] Database locked. Skipping. Error: {oe}")
        session.rollback()
    except Exception as e:
        logging.error(f"[POLLER_ERROR][RoomDBID:{db_id}] Unhandled exception in db_process_poll_data!", exc_info=True)
        session.rollback()
    finally:
        Session.remove()
    return None

def process_cheese_update(room_db_id, new_tracker_data, remote_updated_at):
    """
    Compares new Cheese data against the DB cache. 
    Updates the DB.
    Handles 'Self-Healing' by merging Pending rooms into Real rooms.
    Handles 'Unclaim Sync' by validating current DB tracks against Cheese ownership.
    """
    session = Session()
    
    try:
        room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
        if not room: 
            return {}
        
        is_first_sync = room.cheese_updated_at is None

        # =========================================================================
        # 1. SELF-HEALING & MERGE LOGIC (Existing)
        # =========================================================================
        if room.room_id.startswith("PENDING_DISCOVERY") and new_tracker_data.get('room_link'):
            real_uuid = extract_ap_room_id(new_tracker_data['room_link'])
            if real_uuid:
                # CHECK CONFLICT
                existing_real_room = session.query(TrackedRoom).filter_by(room_id=real_uuid).first()
                if existing_real_room:
                    logging.info(f"[POLLER_MERGE] Merging Pending Room {room.id} into Existing Room {existing_real_room.id}")
                    
                    # A. Pre-fetch children
                    pending_subs = session.query(UserRoomSubscription).filter_by(room_id=room.id).all()
                    pending_slots = session.query(UserTrackedSlot).filter_by(room_id=room.id).all()

                    # B. Release Unique Constraint
                    ct_id_val = room.cheese_tracker_id
                    room.cheese_tracker_id = None
                    session.flush() 

                    # C. Migrate to Real Room
                    existing_real_room.cheese_tracker_id = ct_id_val
                    
                    # Group pending slots by user for easier processing
                    slots_by_user = {}
                    for s in pending_slots:
                        slots_by_user.setdefault(s.user_id, []).append(s)

                    for p_sub in pending_subs:
                        user_id = p_sub.user_id
                        
                        # 1. Ensure a Subscription exists for the NEW room
                        real_sub = session.query(UserRoomSubscription).filter_by(
                            user_id=user_id, room_id=existing_real_room.id
                        ).first()
                        
                        if not real_sub:
                            # If it doesn't exist, we must create it so slots have a valid parent
                            # We copy relevant settings (alias, etc) from the pending subscription
                            real_sub = UserRoomSubscription(
                                user_id=user_id, 
                                room_id=existing_real_room.id,
                                alias=p_sub.alias,
                                is_archived=p_sub.is_archived
                            )
                            session.add(real_sub)
                            # CRITICAL: Flush so the DB knows this ID exists before we move slots to it
                            session.flush()

                        # 2. Move Slots to the New Room
                        user_slots = slots_by_user.get(user_id, [])
                        for p_slot in user_slots:
                            # Check if the destination already has this slot tracked (prevent duplicates)
                            conflict_slot = session.query(UserTrackedSlot).filter_by(
                                 user_id=user_id, room_id=existing_real_room.id, slot_id=p_slot.slot_id
                            ).first()
                            
                            if conflict_slot:
                                # Duplicate detected: Delete the pending one, keep the existing one
                                session.delete(p_slot)
                            else:
                                # Safe to move: Update the room_id
                                p_slot.room_id = existing_real_room.id

                        # 3. Delete the Old Subscription
                        # Now that slots are moved/deleted, p_sub has no children and can be safely removed.
                        session.delete(p_sub)
                    
                    # Finally, delete the old Pending Room
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
                    except Exception: pass

        # =========================================================================
        # 2. UPDATE DB CACHE
        # =========================================================================
        room.cached_cheese_json = json.dumps(new_tracker_data)
        
        current_cheese_time = datetime.utcnow()
        try:
            clean_time = remote_updated_at
            if '.' in clean_time:
                main, frac = clean_time.split('.')
                clean_time = f"{main}.{frac[:6]}"
            # Ensure we are working with a timezone-aware or naive UTC object consistent with your app
            parsed_dt = datetime.fromisoformat(clean_time.replace('Z', '+00:00'))
            
            # Convert to naive UTC if your DB/App uses naive UTC (which api.py seems to imply)
            if parsed_dt.tzinfo:
                parsed_dt = parsed_dt.replace(tzinfo=None)
                
            room.cheese_updated_at = parsed_dt
            current_cheese_time = parsed_dt
        except (ValueError, TypeError):
            room.cheese_updated_at = datetime.utcnow()

        # =========================================================================
        # 3. UNCLAIM SYNC (State-Based) with GRACE PERIOD
        # =========================================================================
        
        new_games_map = {g['position']: g for g in new_tracker_data.get('games', [])}
        
        current_tracked_slots = session.query(UserTrackedSlot).options(
            selectinload(UserTrackedSlot.user) 
        ).filter_by(room_id=room.id).all()

        for ts in current_tracked_slots:
            user = ts.user 
            if not user or not user.cheese_user_id: continue

            game_data = new_games_map.get(ts.slot_id)
            
            if game_data:
                # Case A: Slot exists in Cheese data.
                remote_owner_id = game_data.get('claimed_by_ct_user_id')
                
                # CONFLICT: Someone else owns it. 
                # ALWAYS Prune. Security/Integrity beats Grace Period.
                if remote_owner_id and remote_owner_id != user.cheese_user_id:
                    logging.info(f"[POLLER_SYNC] Untracking Slot {ts.slot_id} (Owner mismatch)")
                    session.delete(ts)
                
                # UNCLAIMED: Remote is None, but we are tracking it.
                elif remote_owner_id is None:
                    # CHECK: Is this the first sync?
                    if is_first_sync:
                         logging.info(f"[POLLER_SYNC] GRACE PERIOD: Keeping Slot {ts.slot_id} (First Sync - Waiting for push).")
                         continue
                    
                    # If not first sync, we assume the user released it on the website.
                    logging.info(f"[POLLER_SYNC] Untracking Slot {ts.slot_id} (Remote is unclaimed).")
                    session.delete(ts)

            else:
                # Case B: Slot is MISSING from Cheese data entirely.
                # This happens if Cheese API returns partial data or during creation.
                # We can also trust is_first_sync here.
                if is_first_sync:
                    logging.info(f"[POLLER_SYNC] GRACE PERIOD: Keeping Slot {ts.slot_id} (Slot missing - First Sync).")
                    continue

                logging.info(f"[POLLER_SYNC] Untracking Slot {ts.slot_id} (Slot vanished from Cheese)")
                session.delete(ts)

        session.commit()
        return {}

    except Exception as e:
        logging.error(f"[POLLER_CHEESE_ERROR] DB Update failed: {e}", exc_info=True)
        session.rollback()
        return {}
    finally:
        Session.remove()

async def run_room_poll(room_info, loop):
    """Runs a single lightweight poll cycle for an already set up room."""
    db_id = room_info['db_id']
    hostname = room_info['hostname']
    
    # 1. Read local state from DB
    room_data = await loop.run_in_executor(None, db_read_room_poll_state, db_id)
    if not room_data: return
        
    tracker_id = room_data['tracker_id']
    room_uuid = room_data['room_uuid']
    last_known_activity = room_data['last_remote_activity']
    cached_address = room_data.get('cached_full_address')

    if not tracker_id: return

    # --- GATEKEEPER START ---
    status_url = f"https://{hostname}/api/room_status/{room_uuid}"
    status_data, status_code = await fetch_json_with_status(status_url)

    # Variables to track what we find
    current_remote_activity = None
    new_full_address = None
    
    # Default to TRUE (Poll) for safety. We only set to False if we prove nothing changed.
    should_fetch_tracker = True

    if status_code == 404:
        await loop.run_in_executor(None, db_suspend_room, db_id, "404 Not Found (Gatekeeper)")
        return # STOP POLLING IMMEDIATELY

    # 2. HANDLE NETWORK FAILURE
    if not status_data:
        # If 404 is handled, any other 'False' means network error or non-200
        # We fail open (poll safely) or skip. For gatekeeper, skipping is safer if we can't check status.
        # But to be safe against "stuck" rooms, we often default to True (Poll) if check fails.
        should_fetch_tracker = True 
    else:
        if status_data:
            # We assume we can skip, then check for any reason to force a poll
            should_fetch_tracker = False
            
            # Reason 1: Tracker ID Mismatch (Re-gen)
            remote_tracker_id = status_data.get('tracker')
            if remote_tracker_id and remote_tracker_id != tracker_id:
                logging.info(f"[POLLER_GATE] Tracker ID mismatch for room {db_id}. Forcing poll.")
                should_fetch_tracker = True

            # Reason 2: Port Mismatch
            remote_port = status_data.get('last_port')
            if remote_port:
                check_address = f"{hostname}:{remote_port}"
                if check_address != cached_address:
                    logging.info(f"[POLLER_GATE] Port changed for Room {db_id} ({cached_address} -> {check_address}). Forcing poll.")
                    new_full_address = check_address
                    should_fetch_tracker = True

            # Reason 3: Timestamp is New (or we can't read it)
            remote_activity_str = status_data.get('last_activity')
            if remote_activity_str:
                try:
                    dt_aware = parsedate_to_datetime(remote_activity_str)
                    current_remote_activity = dt_aware.astimezone(timezone.utc).replace(tzinfo=None)
                    
                    # If remote is NEWER than local, we must poll.
                    # If remote is OLDER or SAME, we don't need to poll (unless reasons 1 or 2 triggered)
                    if not last_known_activity or current_remote_activity > last_known_activity:
                        # Only log debug if it's purely an activity update to avoid spam
                        if not should_fetch_tracker: 
                            logging.debug(f"[POLLER_GATE] New activity detected for Room {db_id}.")
                        should_fetch_tracker = True
                except Exception as e:
                    logging.warning(f"[POLLER_GATE] Date parse error for room {db_id}: {e}")
                    should_fetch_tracker = True # Safety Fallback
            else:
                # Timestamp missing? Safety Fallback.
                should_fetch_tracker = True
        else:
            # Status endpoint failed (404/500)? Safety Fallback.
            should_fetch_tracker = True

    # FINAL DECISION
    if not should_fetch_tracker:
        return
    # --- GATEKEEPER END ---

    start_wait_time = time.time()
    start_wait_time = time.time()

    async with ap_poll_semaphore:
        wait_duration = time.time() - start_wait_time
        if wait_duration > SEMAPHORE_WAIT_WARNING_THRESHOLD:
            logging.warning(f"[HIGH_LOAD] Room {db_id} waited {wait_duration:.2f}s for semaphore.")
            
        # 1. FETCH THE DATA
        tracker_data = await fetch_json(f"https://{hostname}/api/tracker/{tracker_id}")

    # 2. CHECK IF DATA EXISTS
    if not tracker_data:
        return

    # 3. NOW CALCULATE CONNECTED SLOTS (Paste the new logic here)
    connected_slots = set()
    player_statuses_raw = tracker_data.get('player_status', {})

    if isinstance(player_statuses_raw, dict):
        for slot_id, status in player_statuses_raw.items():
            if status == 5:
                connected_slots.add(int(slot_id))
    elif isinstance(player_statuses_raw, list):
        for entry in player_statuses_raw:
            if isinstance(entry, dict) and entry.get('status') == 5:
                pid = entry.get('player')
                if pid is not None:
                    connected_slots.add(int(pid))

    # 4. PASS TO DB PROCESSOR
    try:
        notifications_to_send = await loop.run_in_executor(
            None, 
            db_process_poll_data, 
            db_id, 
            room_uuid, 
            tracker_data, 
            room_data, 
            current_remote_activity,
            new_full_address,
            list(connected_slots) 
        )
        
        if notifications_to_send:
            for user_id, data in notifications_to_send.items():
                logging.info(f"[NOTIFY] Sending {len(data['notifications'])} notification(s) to user {user_id}")
                await send_push_notifications(data['notifications'], data['tokens'], loop)

    except Exception as e:
        logging.error(f"[POLLER_ERROR][RoomDBID:{db_id}] Error in run_room_poll!", exc_info=True)

async def run_cheese_poll(room_info, loop):
    """
    Async task to check Cheese Tracker for updates.
    """
    db_id = room_info['db_id']
    ct_id = room_info['cheese_tracker_id']
    last_updated_at_db = room_info.get('cheese_updated_at') # datetime object or None

    # 1. Fetch Public Data (No Auth needed for reads)
    base_url = os.environ.get('CHEESE_BASE_URL', 'https://cheesetrackers.theincrediblewheelofchee.se/api')
    url = f"{base_url}/tracker/{ct_id}"

    # Use semaphore to limit concurrent requests to Cheese API
    async with cheese_semaphore:
        new_data = await fetch_json(url, headers=get_cheese_headers())
    
    if not new_data: 
        return

    # 2. Timestamp Efficiency Check
    remote_time_str = new_data.get('updated_at')
    if not remote_time_str: 
        return # Should not happen on valid API

    # Convert remote string to compare with DB datetime
    # Simple string comparison is risky due to timezone formatting diffs, 
    # but if the DB stored the exact string, we could compare strings. 
    # For safety, we let the DB Update function handle the decision logic or compare here loosely.
    # Optimization: If we stored the raw string in DB, we could compare here instantly.
    # For now, we proceed to the thread if data exists.
    
    # 3. Offload Processing to Thread
    # The sync function will check if the timestamps match exactly before processing logic
    notifications_payload = await loop.run_in_executor(
        None, 
        process_cheese_update, 
        db_id, 
        new_data, 
        remote_time_str
    )

    # 4. Send Pushes (if any)
    if notifications_payload:
        for user_id, data in notifications_payload.items():
            logging.info(f"[CHEESE_NOTIFY] Sending {len(data['notifications'])} to user {user_id}")
            await send_push_notifications(data['notifications'], data['tokens'], loop)

def db_read_room_poll_state(db_id):
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=db_id).first()
        if not room: return None
        return {
            'room_uuid': room.room_id,
            'tracker_id': room.tracker_id,
            'cached_players_json_str': room.cached_players_json,
            'game_checksums_json_str': room.game_checksums_json,
            'is_complete_status': room.is_complete,
            'last_remote_activity': room.last_remote_activity,
            'cached_full_address': room.cached_full_address,
            'hostname': room.hostname
        }
    except Exception as e:
        return None
    finally:
        Session.remove()

# =============================================================================
# SETUP LOGIC
# =============================================================================

async def run_room_setup(room_info, loop):
    """
    Performs setup for a new room, including fetching static tracker data
    for total check counts.
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
            await loop.run_in_executor(None, db_handle_setup_failure, db_id)
            return
        
        new_tracker_id = room_status.get('tracker')
        if not new_tracker_id:
            logging.warning(f"[POLLER_SETUP_WARN][RoomDBID:{db_id}] No tracker ID found in status. Cannot fetch static data.")
            return
        
        setup_data['tracker_id'] = new_tracker_id

        tracker_url = f"https://{hostname}/api/tracker/{new_tracker_id}"
        tracker_data = await fetch_json(tracker_url)
        
        finished_slots = set()
        if tracker_data:
            statuses = tracker_data.get('player_status', {})
            if isinstance(statuses, dict):
                finished_slots = {int(p) for p, s in statuses.items() if s == 30}
            elif isinstance(statuses, list):
                for s in statuses:
                    if isinstance(s, dict) and s.get('status') == 30:
                        finished_slots.add(s.get('player'))

        static_tracker_url = f"https://{hostname}/api/static_tracker/{new_tracker_id}"
        static_data = await fetch_json(static_tracker_url)

        if not static_data:
             logging.warning(f"[POLLER_SETUP_WARN][RoomDBID:{db_id}] Failed to fetch static tracker data. Aborting setup to avoid saving 0s.")
             return
        
        totals_map = {}
        if static_data and 'player_locations_total' in static_data:
            for entry in static_data['player_locations_total']:
                if 'player' in entry and 'total_locations' in entry:
                    totals_map[entry['player']] = entry['total_locations']

        players_raw = room_status.get('players', [])
        player_list = []
        for i, p in enumerate(players_raw):
            slot_id = i + 1
            player_list.append({
                'slot_id': slot_id, 
                'name': p[0], 
                'game': p[1],
                'total_locations': totals_map.get(slot_id, 0),
                'is_finished': slot_id in finished_slots
            })
        
        setup_data['cached_players_json'] = json.dumps(player_list)
        setup_data['cached_total_slots'] = len(player_list)
        setup_data['cached_full_address'] = f"{hostname}:{room_status.get('last_port', '')}"
        setup_data['last_api_check'] = datetime.utcnow()

        port = room_status.get('last_port')
        checksums = {}

        if port:
            uris_to_try = [
                f"wss://{hostname}:{port}",
                f"ws://{hostname}:{port}"
            ]
            
            parts = hostname.split('.')
            base_domain = None 
            
            if len(parts) > 2:
                base_domain = ".".join(parts[1:])
                uris_to_try.extend([
                    f"wss://{base_domain}:{port}",
                    f"ws://{base_domain}:{port}"
                ])

            max_ws_retries = 2
            ws_success = False

            for uri in uris_to_try:
                if ws_success:
                    break
                    
                for attempt in range(1, max_ws_retries + 1):
                    try:
                        logging.debug(f"[POLLER_SETUP] WebSocket attempt {attempt}/{max_ws_retries} for {uri}")
                        session = get_aiohttp_session()
                        async with session.ws_connect(uri, timeout=5) as ws:
                            msg = await ws.receive(timeout=5)
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                room_info_msg = json.loads(msg.data)
                                checksums = room_info_msg[0].get('datapackage_checksums', {})
                                ws_success = True
                            
                                # Safely check if base_domain exists before using it
                                if base_domain and (uri.startswith(f"wss://{base_domain}") or uri.startswith(f"ws://{base_domain}")):
                                    setup_data['cached_full_address'] = f"{base_domain}:{port}"

                                break
                            
                    except Exception as ws_e:
                        logging.warning(f"[POLLER_SETUP_WARN][RoomDBID:{db_id}] WebSocket attempt {attempt} failed for {uri}: {ws_e}")
                        
                        # Only wait to wake the room if we are on the final attempt of the CURRENT uri
                        if attempt < max_ws_retries:
                            await _attempt_room_wake(hostname, room_uuid)
                            logging.info(f"[POLLER_SETUP] Waiting 8 seconds for room to wake up...")
                            await asyncio.sleep(8)
                        else:
                            logging.info(f"[POLLER_SETUP_INFO][RoomDBID:{db_id}] Exhausted attempts for {uri}.")

            if not ws_success:
                 logging.warning(f"[POLLER_SETUP_WARN][RoomDBID:{db_id}] Falling back to HTTP checksums.")
                 checksums = room_status.get('datapackage_checksums', {})

        if not checksums:
            logging.warning(f"[POLLER_SETUP_WARN][RoomDBID:{db_id}] No checksums found (WS and HTTP failed). Aborting setup.")
            # Trigger failure count so it eventually suspends if this persists
            await loop.run_in_executor(None, db_handle_setup_failure, db_id)
            return

        new_checksums_json_str = json.dumps(checksums)
        datapackage_entries_by_game = {}

        if checksums:
            logging.debug(f"[POLLER_SETUP_DEBUG][RoomDBID:{db_id}] Fetching datapackages...")
            checksums_to_check = set(checksums.values())
            existing_in_db = await loop.run_in_executor(None, db_check_existing_checksums, checksums_to_check)
            new_checksums_to_fetch = checksums_to_check - existing_in_db

            for game, checksum in checksums.items():
                if checksum in new_checksums_to_fetch: 
                    game_data = await fetch_json(f"https://{hostname}/api/datapackage/{checksum}")
                    if not game_data: continue
                    
                    current_game_entries = []
                    actual_data = game_data.get('games', {}).get(game, game_data)
                    
                    seen_ids = set() 

                    # 1. Process Items
                    for n, eid in actual_data.get('item_name_to_id', {}).items():
                        if ('item', eid) in seen_ids:
                            continue # Skip duplicate/alias
                        
                        seen_ids.add(('item', eid))
                        current_game_entries.append(DatapackageCache(
                            game=game, checksum=checksum, entity_type='item', entity_id=eid, entity_name=n
                        ))

                    # 2. Process Locations
                    for n, eid in actual_data.get('location_name_to_id', {}).items():
                        if ('location', eid) in seen_ids:
                             continue # Skip duplicate/alias
                        
                        seen_ids.add(('location', eid))
                        current_game_entries.append(DatapackageCache(
                            game=game, checksum=checksum, entity_type='location', entity_id=eid, entity_name=n
                        ))
                    
                    if current_game_entries:
                        datapackage_entries_by_game[game] = current_game_entries
            
            if datapackage_entries_by_game:
                setup_data['datapackage_entries_by_game'] = datapackage_entries_by_game
            
            setup_data['game_checksums_json'] = new_checksums_json_str

        setup_data['is_setup'] = True 
        logging.info(f"[POLLER_SETUP][RoomDBID:{db_id}] Setup complete.")

    except Exception as e:
        logging.error(f"[POLLER_SETUP_ERROR][RoomDBID:{db_id}] Setup error: {e}", exc_info=True)
        return 

    try:
        await loop.run_in_executor(None, db_commit_setup_data, db_id, setup_data)
    except Exception as e:
        logging.error(f"[POLLER_SETUP_ERROR][RoomDBID:{db_id}] Failed to commit setup data: {e}", exc_info=True)

def db_check_existing_checksums(checksums_to_check):
    session = Session()
    try:
        existing = set(c[0] for c in session.query(DatapackageCache.checksum).filter(DatapackageCache.checksum.in_(checksums_to_check)).distinct())
        return existing
    except Exception:
        logging.error(f"[POLLER_DB_ERROR] Failed to check existing checksums: {e}")
        return set()
    finally:
        Session.remove()

def db_commit_setup_data(db_id, setup_data):
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=db_id).first()
        if not room: 
            logging.warning(f"[POLLER_DB_ERROR][RoomDBID:{db_id}] Room vanished before setup commit.")
            return
        
        room.failed_poll_count = 0

        if 'cached_players_json' in setup_data: room.cached_players_json = setup_data['cached_players_json']
        if 'cached_total_slots' in setup_data: room.cached_total_slots = setup_data['cached_total_slots']
        if 'cached_full_address' in setup_data: room.cached_full_address = setup_data['cached_full_address']
        if 'last_api_check' in setup_data: room.last_api_check = setup_data['last_api_check']
        if 'tracker_id' in setup_data: room.tracker_id = setup_data['tracker_id']
        if 'game_checksums_json' in setup_data: room.game_checksums_json = setup_data['game_checksums_json']
        if setup_data.get('is_setup'): room.is_setup = True

        session.commit()
        
        if setup_data.get('datapackage_entries_by_game'):
            # Iterate over games one by one
            for game, entries in setup_data['datapackage_entries_by_game'].items():
                try:
                    chunk_size = 500 
                    total_entries = len(entries)
                    
                    for i in range(0, total_entries, chunk_size):
                        chunk = entries[i:i + chunk_size]
                        session.bulk_save_objects(chunk)
                        session.commit()
                        
                    logging.info(f"[POLLER_SETUP] Successfully cached {total_entries} entities for {game}.")
                        
                except IntegrityError:
                    session.rollback()
                    logging.warning(f"[POLLER_DB_WARN] Duplicate datapackage data for {game}, skipping.")
                except Exception as e:
                    session.rollback()
                    logging.error(f"[POLLER_DB_ERROR] Failed to save datapackage for {game}: {e}", exc_info=True)

    except Exception as e:
        session.rollback()
        raise e
    finally:
        Session.remove()

def db_handle_setup_failure(db_id):
    """
    Synchronously increments the failure count for a room during setup.
    If it exceeds the limit, suspends the room to stop the error loop.
    """
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=db_id).first()
        if not room:
            return

        room.failed_poll_count += 1
        
        if room.failed_poll_count >= 5:
            room.is_suspended = True
            logging.warning(f"[POLLER_ACTION][RoomDBID:{db_id}] Suspended room after repeated setup failures.")
        
        session.commit()
    except Exception as e:
        logging.error(f"[POLLER_DB_ERROR] Failed to handle setup failure: {e}")
        session.rollback()
        raise e
    finally:
        Session.remove()


# =============================================================================
# SUPERVISOR & WORKERS
# =============================================================================

async def poll_room_with_interval(room_info, loop):
    await asyncio.sleep(random.uniform(1, 45))
    while True:
        try:
            await run_room_poll(room_info, loop)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"[POLLER_ERROR] Interval error: {e}", exc_info=True)
        
        try:
            await asyncio.sleep(POLLING_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            break

async def poll_cheese_with_interval(room_info, loop):
    """
    Dedicated loop for Cheese polling to keep it independent of AP polling errors.
    """
    # Stagger start slightly to avoid thundering herd with AP poll
    await asyncio.sleep(random.randint(5, 60))    
    
    while True:
        try:
            await run_cheese_poll(room_info, loop)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"[CHEESE_LOOP_ERROR] {room_info['db_id']}: {e}")
        
        try:
            # Use the same interval, or a different one (e.g. 3 minutes)
            await asyncio.sleep(POLLING_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            break

async def setup_worker(setup_queue, setup_semaphore, rooms_in_setup, loop):
    while True:
        room_info = None
        try:
            room_info = await setup_queue.get()
            async with setup_semaphore:
                await run_room_setup(room_info, loop)
        except (asyncio.CancelledError, RuntimeError):
            # Graceful shutdown or loop closed
            break
        except Exception as e:
            logging.error(f"[SETUP_WORKER_ERROR] Unhandled error: {e}", exc_info=True)
        finally:
            if room_info:
                rooms_in_setup.discard(room_info['db_id'])
                try:
                    setup_queue.task_done()
                except (ValueError, RuntimeError):
                    pass # Loop might be closing

async def poller_supervisor(app, loop):
    logging.info("[POLLER] Background polling service starting...")
    running_tasks = {}
    last_cleanup_time = datetime.utcnow()

    setup_queue = asyncio.Queue()
    setup_semaphore = asyncio.Semaphore(2) 
    rooms_in_setup = set()
    
    asyncio.create_task(setup_worker(setup_queue, setup_semaphore, rooms_in_setup, loop))
    asyncio.create_task(setup_worker(setup_queue, setup_semaphore, rooms_in_setup, loop))
    
    while True:
        try:
            log_resource_usage(app)
            active_rooms_in_db = await loop.run_in_executor(None, db_get_active_rooms)
            
            if active_rooms_in_db is None:
                await asyncio.sleep(SUPERVISOR_INTERVAL_SECONDS)
                continue
                
            current_active_room_ids = {room.id for room in active_rooms_in_db}
            
            for room in active_rooms_in_db:
                room_info = {
                    'db_id': room.id, 
                    'hostname': room.hostname, 
                    'room_uuid': room.room_id,
                    'cheese_tracker_id': room.cheese_tracker_id,
                    'cheese_updated_at': room.cheese_updated_at
                }
                
                # --- GUARD: Check if this is a "Cheese Only" / Pending room ---
                is_pending_discovery = room.room_id.startswith("PENDING_DISCOVERY")

                # --- 1. Archipelago Task ---
                # ONLY run this if we have a real Room ID
                if not is_pending_discovery:
                    is_missing_data = not room.tracker_id or not room.game_checksums_json or room.game_checksums_json == '{}'
                    has_total_locations = '"total_locations":' in (room.cached_players_json or "")
                    
                    needs_setup = (not room.is_setup) or (room.is_setup and is_missing_data) or (not has_total_locations)

                    if needs_setup:
                        if room.id not in running_tasks and room.id not in rooms_in_setup:
                            logging.info(f"[SUPERVISOR] Queuing room {room.id} for setup.")
                            rooms_in_setup.add(room.id)
                            await setup_queue.put(room_info)
                            # THROTTLE: Stagger setup queuing
                            await asyncio.sleep(0.02)

                        elif room.id in running_tasks and room.id not in rooms_in_setup:
                            logging.info(f"[SUPERVISOR] Re-queuing running room {room.id} for metadata repair.")
                            rooms_in_setup.add(room.id)
                            await setup_queue.put(room_info)
                            # THROTTLE: Stagger setup repair
                            await asyncio.sleep(0.02)
                    else:
                        if room.id not in running_tasks:
                            logging.info(f"[SUPERVISOR] Starting AP poller for room {room.id}")
                            task = asyncio.create_task(poll_room_with_interval(room_info, loop))
                            running_tasks[room.id] = task
                            # THROTTLE: Stagger poller startup (Thundering Herd Fix)
                            await asyncio.sleep(0.02)
                
                # --- 2. Cheese Task ---
                # We run this regardless of AP status (even if Pending!)
                cheese_task_key = f"cheese_{room.id}"
                
                if room.cheese_tracker_id:
                    if cheese_task_key not in running_tasks:
                        logging.info(f"[SUPERVISOR] Starting Cheese poller for room {room.id}")
                        c_task = asyncio.create_task(poll_cheese_with_interval(room_info, loop))
                        running_tasks[cheese_task_key] = c_task
                        # THROTTLE: Stagger cheese startup
                        await asyncio.sleep(0.02)
                else:
                    if cheese_task_key in running_tasks:
                        running_tasks[cheese_task_key].cancel()
                        del running_tasks[cheese_task_key]

            # Cleanup inactive tasks
            active_task_keys = current_active_room_ids.union(
                {f"cheese_{rid}" for rid in current_active_room_ids}
            )
            
            inactive_keys = set(running_tasks.keys()) - active_task_keys
            for key in inactive_keys:
                logging.info(f"[SUPERVISOR] Stopping poller task {key}.")
                task_to_stop = running_tasks.pop(key, None)
                if task_to_stop:
                    task_to_stop.cancel()

            if datetime.utcnow() - last_cleanup_time > timedelta(hours=24):
                # 1. Delete orphaned rooms (No subscribers)
                await loop.run_in_executor(None, db_run_cleanup)
                
                # 2. Suspend stale active rooms (Has subscribers, but no activity)
                await loop.run_in_executor(None, db_check_stale_rooms)
                
                last_cleanup_time = datetime.utcnow()

        except Exception as e:
            logging.error(f"[SUPERVISOR] An unhandled error occurred: {e}", exc_info=True)

        await asyncio.sleep(SUPERVISOR_INTERVAL_SECONDS)

def db_get_active_rooms():
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
    session = Session()
    try:
        # 1. Clean up Orphaned Rooms (Existing Logic)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        rooms_to_delete = session.query(TrackedRoom).filter(
            TrackedRoom.subscriptions.any() == False,
            or_(
                TrackedRoom.last_successful_poll == None,
                TrackedRoom.last_successful_poll < thirty_days_ago
            )
        ).all()
        for room in rooms_to_delete:
            session.delete(room)
        
        # 2. Clean up Stale Guest Accounts (e.g., > 30 days inactive)
        # We ONLY delete 'is_guest' users. We never touch Discord users.
        stale_guests = session.query(User).filter(
            User.is_guest == True,
            User.last_activity < thirty_days_ago
        ).all()

        if stale_guests:
            logging.info(f"[JANITOR] Pruning {len(stale_guests)} stale guest accounts.")
            for guest in stale_guests:
                session.delete(guest) # Cascade deletes their subscriptions/devices too

        session.commit()
    except Exception as e:
        logging.error(f"[JANITOR_DB_ERROR] Failed to run cleanup: {e}", exc_info=True)
        session.rollback()
    finally:
        Session.remove()

def run_poller(app):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main_task = loop.create_task(poller_supervisor(app, loop))
    try:
        loop.run_until_complete(main_task)
    except Exception as e:
        logging.critical(f"[POLLER_CRITICAL] asyncio.run() failed: {e}", exc_info=True)
    finally:
        loop.run_until_complete(close_aiohttp_session())
        loop.close()

def db_check_stale_rooms():
    """
    Suspends rooms that have had NO activity (Items or Hints) for 30 days.
    Sets failed_poll_count to 0 to differentiate from connection errors.
    """
    session = Session()
    try:
        limit_date = datetime.utcnow() - timedelta(days=30)
        
        # Only check rooms that are currently Active
        active_rooms = session.query(TrackedRoom).filter(
            TrackedRoom.is_complete == False,
            TrackedRoom.is_suspended == False
        ).all()
        
        stale_count = 0
        for room in active_rooms:
            # 1. Get latest Item time
            last_item = session.query(NotifiedItem.timestamp).filter_by(room_id=room.room_id).order_by(NotifiedItem.timestamp.desc()).first()
            last_item_time = last_item[0] if last_item else None
            
            # 2. Get latest Hint time
            last_hint = session.query(NotifiedHint.timestamp).filter_by(room_id=room.room_id).order_by(NotifiedHint.timestamp.desc()).first()
            last_hint_time = last_hint[0] if last_hint else None
            
            # 3. Determine latest activity
            latest_activity = None
            if last_item_time and last_hint_time:
                latest_activity = max(last_item_time, last_hint_time)
            elif last_item_time:
                latest_activity = last_item_time
            elif last_hint_time:
                latest_activity = last_hint_time
            
            # 4. Check vs Limit
            # Note: We enforce naive UTC comparison by stripping info if present, or assuming native is UTC.
            # (Adjust based on your DB driver behavior, assuming naive UTC for now as per api.py)
            if latest_activity:
                if latest_activity.tzinfo:
                    latest_activity = latest_activity.replace(tzinfo=None)
                
                if latest_activity < limit_date:
                    room.is_suspended = True
                    room.failed_poll_count = 0 # Distinct from Error Suspension (which is >= 60)
                    stale_count += 1
                    logging.info(f"[POLLER_STALE] Suspending Room {room.id} due to inactivity (Last Active: {latest_activity})")

        if stale_count > 0:
            session.commit()
            logging.info(f"[POLLER_STALE] Suspended {stale_count} stale rooms.")
            
    except Exception as e:
        logging.error(f"[POLLER_STALE_ERROR] Failed to check stale rooms: {e}", exc_info=True)
        session.rollback()
    finally:
        Session.remove()

def compress_notifications(user_notifications, user_prefs, slot_prefs_map):
    """
    Combines notifications of the same type if the user has 'combine_notifications' enabled.
    """
    # 1. Check if we should combine
    # We use the user default, unless the specific slot involved overrides it. 
    # Since a batch might involve multiple slots, we'll stick to the Global Default 
    # or the default of the first tracked slot found in the batch to keep it simple.
    should_combine = user_prefs.combine_notifications_default
    remove_emojis = user_prefs.remove_emojis_default

    # Simple check: if NO notifications, return empty
    if not user_notifications: return []
    
    if not should_combine:
        return user_notifications

    # 2. Group by Type
    items = []
    hints = []
    finishes = []
    others = []

    for n in user_notifications:
        t = n.get('type')
        if t in ['item_progression', 'item_useful']:
            items.append(n)
        elif t == 'hint':
            hints.append(n)
        elif t == 'player_finish':
            finishes.append(n)
        else:
            others.append(n)

    compressed = []
    compressed.extend(others) # Pass through unknown types

    # 3. Helper to squash
    def squash(notif_list, title_base):
        if not notif_list: return
        if len(notif_list) == 1:
            compressed.append(notif_list[0])
            return
        
        # We will grab the room alias from the first item
        first_title = notif_list[0]['title']
        room_suffix = ""
        if " - [" in first_title:
            room_suffix = first_title.split(" - [")[-1]
            room_suffix = " - [" + room_suffix

        item_strings = []
        for n in notif_list:
            if 'item_context' in n:
                ctx = n['item_context']
                # Format: "Item Name [Alias (Original)]"
                formatted = f"{ctx['item_name']} [{ctx['original']}]"
                item_strings.append(formatted)
            else:
                # Fallback to old parsing if context is missing (safety net)
                raw = n['title'].split(" - [")[0]
                clean = raw.replace("🏆 ", "").replace("✅ ", "").replace("💡 ", "")
                item_strings.append(clean)

        count = len(item_strings)
        
        # Show up to 5 items in the collapsed body text
        VISIBLE_LIMIT = 5 
        display_names = item_strings[:VISIBLE_LIMIT]
        remainder = count - VISIBLE_LIMIT
        
        body_str = ", ".join(display_names)
        if remainder > 0:
            body_str += f", and {remainder} others"
        
        final_title = f"{title_base} ({count}){room_suffix}"
        
        compressed.append({
            'title': final_title,
            'body': body_str,
            'type': notif_list[0]['type'],
            'bundled_items': json.dumps(item_strings) 
        })

    t_items = "New Items" if remove_emojis else "📦 New Items"
    t_hints = "New Hints" if remove_emojis else "💡 New Hints"
    t_finish = "Finished" if remove_emojis else "🏁 Finished"

    squash(items, t_items)
    squash(hints, t_hints)
    squash(finishes, t_finish)

    return compressed