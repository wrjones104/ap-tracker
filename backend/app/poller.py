import asyncio
import logging
import aiohttp
import json
import websockets
import os
import random
from dotenv import load_dotenv
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
from threading import local
from sqlalchemy import or_, exc, tuple_
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import OperationalError, IntegrityError

from . import Session, get_firebase_app, process
from .models import (
    User, Device, TrackedRoom, UserRoomSubscription, UserTrackedSlot,
    DatapackageCache, NotifiedItem, NotifiedHint
)

from . import POLLING_INTERVAL_SECONDS, SUPERVISOR_INTERVAL_SECONDS

thread_local_data = local()
load_dotenv()

# =============================================================================
# CORE HELPERS & SETUP
# =============================================================================

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
    finished_player_ids = set()
    notifications_by_user = {}

    # 1. Parse Status from 'player_status'
    player_statuses_raw = tracker_data.get('player_status', {})
    if isinstance(player_statuses_raw, dict): 
        finished_player_ids.update({int(p) for p, s in player_statuses_raw.items() if s == 30})
    elif isinstance(player_statuses_raw, list):
            for status_info in player_statuses_raw:
                if isinstance(status_info, dict) and status_info.get('status') == 30 and 'player' in status_info:
                    finished_player_ids.add(status_info.get('player'))

    # 2. Parse 'player_checks_done'
    checks_done_map = {} 
    player_checks_data = tracker_data.get('player_checks_done', [])
    if isinstance(player_checks_data, list):
        for entry in player_checks_data:
            if 'player' in entry and 'locations' in entry:
                    checks_done_map[entry['player']] = len(entry['locations'])

    # 3. Mathematical Check (Total Locations vs Checks Done)
    for player in players_list:
        pid = player.get('slot_id')
        total = player.get('total_locations', 0)
        done = checks_done_map.get(pid, 0)
        
        if total > 0 and done >= total:
            finished_player_ids.add(pid)

    # 4. Determine newly finished players
    players_just_marked_finished = set()
    players_list_updated = False

    for player in players_list:
        if player.get('slot_id') in finished_player_ids and not player.get('is_finished'):
            player['is_finished'] = True
            players_list_updated = True
            players_just_marked_finished.add(player.get('slot_id'))

    if players_list_updated:
        logging.info(f"[POLLER_ACTION][RoomDBID:{room_db_id}] {len(players_just_marked_finished)} player(s) just finished.")

    # 5. Generate Notifications
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
            
            # Determine Condensed Preference for this user batch
            # We use the preference of the FIRST slot in the batch to decide the format for the whole group
            # (Edge case: user wants mixed formats for different slots finishing simultaneously, but rare)
            use_condensed = user_prefs.use_condensed_messages_default
            first_slot_id = finished_slot_ids[0]
            first_slot_prefs = prefs_by_user_slot.get(user_id, {}).get(first_slot_id)
            if first_slot_prefs and first_slot_prefs.use_condensed_messages is not None:
                use_condensed = first_slot_prefs.use_condensed_messages

            current_name_map = short_name_map if use_condensed else full_name_map

            for slot_id in finished_slot_ids:
                slot_prefs = prefs_by_user_slot.get(user_id, {}).get(slot_id)
                if not slot_prefs: continue 

                if (user_id, slot_id) in backfill_check_set:
                    logging.info(f"[NOTIFY_SKIP][RoomDBID:{room_db_id}] User {user_id} tracking Slot {slot_id} is backfilling. Suppressing 'Finished' notification.")
                    continue 
                
                # Check notify_finished preference
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
            notifications_by_user.setdefault(user_id, []).append({
                'title': f"🏁 Player(s) Finished!",
                'body': f"{player_names_str} has finished in '{alias}'!",
                'type': 'player_finish',
                'details': (room_db_id, user_id, player_names_str)
            })
            
    return notifications_by_user, finished_player_ids, players_list_updated

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
                item_flags=flags
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
                logging.debug(f"[POLLER_DEBUG] Hint skipped due to flags: {flags}")
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
                    is_found=is_found_from_tracker
                ))
                hints_in_this_batch.add(hint_key_batch)
                hints_added_count += 1

                if has_hint_history:
                    io_game = game_map.get(io_id, "Unknown")
                    lo_game = game_map.get(lo_id, "Unknown")
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
                    just_found_hint_item_loc_pairs.add((loc_id, item_id))
    
    if hints_processed_count > 0:
         logging.debug(f"[POLLER_DEBUG][RoomDBID:{room_db_id}] Hints: Proc={hints_processed_count}, SkipClass={hints_skipped_classification}, Added={hints_added_count}")
    if hints_skipped_backfill > 0:
        logging.info(f"[POLLER_INFO][RoomDBID:{room_db_id}] Suppressed {hints_skipped_backfill} hint notifications (backfill).")

    return hints_to_add, new_hints_for_notify, cache_keys_to_fetch, just_found_hint_item_loc_pairs

def _resolve_names_and_notify(session, room_db_id, cache_keys_to_fetch, new_items_for_notify, new_hints_for_notify, users_by_id, prefs_by_user_slot, tracked_slots_by_user, aliases_by_user, full_name_map, short_name_map, backfill_check_set, just_found_hint_item_loc_pairs, finished_player_ids):
    """
    Fetches names from DB in chunks and constructs final notification payloads.
    Applies filtering, backfill checks, ignore lists, and alias/condensed formatting.
    """
    notifications_by_user = {}
    name_lookup_map = {}

    # 1. Fetch Names from DatapackageCache
    if cache_keys_to_fetch:
        logging.debug(f"[POLLER_DEBUG][RoomDBID:{room_db_id}] Fetching {len(cache_keys_to_fetch)} names...")
        try:
            keys_list = list(cache_keys_to_fetch)
            chunk_size = 500
            for i in range(0, len(keys_list), chunk_size):
                chunk = keys_list[i:i + chunk_size]
                results = session.query(
                    DatapackageCache.game, DatapackageCache.checksum,
                    DatapackageCache.entity_type, DatapackageCache.entity_id,
                    DatapackageCache.entity_name
                ).filter(tuple_(
                    DatapackageCache.game, DatapackageCache.checksum,
                    DatapackageCache.entity_type, DatapackageCache.entity_id
                ).in_(chunk))
                for game, chk, etype, eid, name in results:
                    name_lookup_map[(game, chk, etype, eid)] = name
        except Exception as e:
            logging.error(f"[POLLER_DB_ERROR][RoomDBID:{room_db_id}] Failed to bulk-fetch names: {e}", exc_info=True)
            return {}

    # 2. Notify Items
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
        rid = item_data['receiving_slot_id']
        send_id = item_data['sending_slot_id']
        is_a_found_hint = (loc_id, item_id) in just_found_hint_item_loc_pairs

        for user_id, tracked_slots in tracked_slots_by_user.items():
            if rid in tracked_slots:
                if rid == send_id:
                     logging.info(f"[NOTIFY_SUPPRESSED] User {user_id} suppressed local item '{item_name}' (Slot {rid} found its own item).")
                     continue
                
                alias = aliases_by_user.get(user_id, "Unknown Room")
                user_prefs = users_by_id.get(user_id)
                slot_prefs = prefs_by_user_slot.get(user_id, {}).get(rid)

                if not user_prefs or not slot_prefs: continue

                # Check Finished Suppression
                wants_finished_notifs = slot_prefs.notify_finished if slot_prefs.notify_finished is not None else user_prefs.notify_finished_default
                if rid in finished_player_ids and not wants_finished_notifs:
                    logging.info(f"[NOTIFY_SUPPRESSED] User {user_id} suppressed item for Slot {rid} (Slot Finished).")
                    continue

                # Check Backfill Suppression
                if (user_id, rid) in backfill_check_set:
                    logging.info(f"[NOTIFY_SKIP][RoomDBID:{room_db_id}] User {user_id} tracking Slot {rid} is backfilling. Suppressing item {item_data['item_id']}.")
                    continue

                # --- IGNORE LIST CHECK START ---
                normalized_item_name = item_name.lower().strip()
                should_ignore = False
                
                if user_prefs.ignore_items:
                    for ignore_rule in user_prefs.ignore_items:
                        # 1. Check Item Name Match
                        if ignore_rule.item_name.lower().strip() == normalized_item_name:
                            # 2. Check Game Scope
                            if not ignore_rule.game_name:
                                should_ignore = True
                                break
                            elif ignore_rule.game_name.lower().strip() == item_data['receiver_game'].lower().strip():
                                should_ignore = True
                                break
                
                if should_ignore:
                    logging.info(f"[NOTIFY_SUPPRESSED] User {user_id} ignored item '{item_name}' for game '{item_data['receiver_game']}'.")
                    continue
                # --- IGNORE LIST CHECK END ---

                # --- CONDENSED MESSAGING CHECK ---
                use_condensed = user_prefs.use_condensed_messages_default
                if slot_prefs.use_condensed_messages is not None:
                    use_condensed = slot_prefs.use_condensed_messages

                current_name_map = short_name_map if use_condensed else full_name_map
                sender_name = current_name_map.get(send_id, f'P{send_id}')
                receiver_name = current_name_map.get(rid, f'P{rid}')

                # Build Body based on Preference
                if use_condensed:
                    body = f"Sent to {receiver_name} by {sender_name}"
                else:
                    body = f"{sender_name} sent {item_name} to {receiver_name} ({loc_name})"

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
                
                if should_notify:
                    notifications_by_user.setdefault(user_id, []).append({
                        'title': title, 'body': body, 'type': item_type, 'details': item_data['item_key_batch']
                    })

    # 3. Notify Hints
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
            is_for_us = io_id in tracked_slots
            is_at_our_location = lo_id in tracked_slots

            if is_for_us or is_at_our_location:
                
                # --- STRICT SAME-WORLD SUPPRESSION ---
                if io_id == lo_id:
                    logging.debug(f"[POLLER_DEBUG] Skipped Hint {hint_data['item_id']} for User {user_id}: Self-hint (Item Owner == Location Owner).")
                    continue

                # Determine User Preferences
                user_prefs = users_by_id.get(user_id)
                if not user_prefs: continue

                relevant_slot = io_id if is_for_us else lo_id

                # Determine if user wants notifications for finished slots
                relevant_slot_prefs = prefs_by_user_slot.get(user_id, {}).get(relevant_slot)
                wants_finished_notifs = user_prefs.notify_finished_default
                if relevant_slot_prefs and relevant_slot_prefs.notify_finished is not None:
                    wants_finished_notifs = relevant_slot_prefs.notify_finished

                if relevant_slot in finished_player_ids and not wants_finished_notifs:
                    logging.info(f"[NOTIFY_SUPPRESSED] User {user_id} suppressed hint for Slot {relevant_slot} (Slot Finished).")
                    continue
                
                should_send_notification = False

                # Rule 1: Hints for MY Items (is_for_us)
                if is_for_us:
                    wants_remote = getattr(user_prefs, 'notify_hints_remote_items_default', True)
                    if relevant_slot_prefs and relevant_slot_prefs.notify_hints_remote_items is not None:
                        wants_remote = relevant_slot_prefs.notify_hints_remote_items
                    if wants_remote:
                        should_send_notification = True

                # Rule 2: Hints for Items in MY World (is_at_our_location)
                if is_at_our_location and not should_send_notification:
                    wants_local = user_prefs.notify_hints_default
                    if relevant_slot_prefs and relevant_slot_prefs.notify_hints is not None:
                         wants_local = relevant_slot_prefs.notify_hints
                    if wants_local:
                        should_send_notification = True
                
                if not should_send_notification:
                    continue

                # Check Backfill (using the slot that triggered the rule)
                relevant_slot_for_backfill = io_id if (is_for_us and should_send_notification) else lo_id
                if (user_id, relevant_slot_for_backfill) in backfill_check_set:
                    logging.debug(f"[POLLER_DEBUG] Skipped Hint {hint_data['item_id']} for User {user_id}: Slot {relevant_slot_for_backfill} is backfilling.")
                    continue

                # --- CONDENSED MESSAGING CHECK ---
                use_condensed = user_prefs.use_condensed_messages_default
                if relevant_slot_prefs and relevant_slot_prefs.use_condensed_messages is not None:
                    use_condensed = relevant_slot_prefs.use_condensed_messages

                current_name_map = short_name_map if use_condensed else full_name_map
                
                # --- BUILD NOTIFICATION ---
                alias = aliases_by_user.get(user_id, "Unknown Room")
                hint_type_icon = "🏆" if (hint_data.get('flags', 0) & 1) else "✅"
                title = f"💡 {hint_type_icon} New Hint! - [{alias}]"
                
                item_owner_name = current_name_map.get(io_id, f'P{io_id}')
                location_owner_name = current_name_map.get(lo_id, f'P{lo_id}')
                
                body = f"{item_owner_name}'s {item_name} is at {loc_name} in {location_owner_name}'s World"
                
                notifications_by_user.setdefault(user_id, []).append({
                    'title': title, 'body': body, 'type': 'hint', 'details': hint_data['hint_key_batch']
                })
    
    return notifications_by_user


def db_process_poll_data(db_id, room_uuid, tracker_data, room_data):
    """
    Synchronously processes tracker data and updates the database.
    Refactored to orchestrate logic via helper functions.
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
        
        # 1. Load existing player cache
        players = json.loads(cached_players_json_str if cached_players_json_str else '[]')
        game_checksums = json.loads(game_checksums_json_str if game_checksums_json_str else '{}')

        aliases_raw = tracker_data.get('aliases', [])
        alias_map = {}
        
        if isinstance(aliases_raw, list):
            for entry in aliases_raw:
                if entry.get('alias') and 'player' in entry:
                    alias_map[entry['player']] = entry['alias']

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

        all_tracked_slots_in_room = session.query(UserTrackedSlot).filter_by(room_id=db_id).all()
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
        aliases_by_user = {sub.user_id: sub.alias for sub in session.query(UserRoomSubscription).filter(UserRoomSubscription.user_id.in_(all_user_ids_in_room), UserRoomSubscription.room_id == db_id)}

        # --- LOGIC STEP 1: Check Player Completions ---
        finish_notifs, finished_player_ids, players_updated_finished = _check_player_completion(
            tracker_data, players, db_id, users_by_id, prefs_by_user_slot, 
            tracked_slots_by_user, backfill_check_set, full_name_map, short_name_map, aliases_by_user
        )
        
        if players_updated_finished or players_updated_local:
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
            backfill_check_set, just_found_hints, finished_player_ids
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
                logging.info(f"[POLLER][RoomDBID:{db_id}] Silently backfilled {len(items_to_add)} historical items.")
            elif not new_items_notif: 
                logging.info(f"[POLLER][RoomDBID:{db_id}] Silently added {len(items_to_add)} new items (Suppressed/Untracked).")

        if hints_to_add:
            session.bulk_save_objects(hints_to_add)
            if not has_hint_history:
                logging.info(f"[POLLER][RoomDBID:{db_id}] Silently backfilled {len(hints_to_add)} historical hints.")

        if slots_to_clear_backfill:
            logging.info(f"[POLLER_ACTION][RoomDBID:{db_id}] Clearing 'needs_backfill' for {len(slots_to_clear_backfill)} slots.")
            for slot in slots_to_clear_backfill:
                slot.needs_backfill = False

        final_payloads = {}
        if notifications_to_send:
            devices_to_notify = session.query(Device).filter(Device.user_id.in_(notifications_to_send.keys())).all()
            tokens_by_user = {}
            for device in devices_to_notify: 
                tokens_by_user.setdefault(device.user_id, []).append(device.fcm_token)

            for user_id, notifications in notifications_to_send.items():
                user_tokens = tokens_by_user.get(user_id)
                if user_tokens:
                    unique_notifications = list({json.dumps(d): d for d in notifications}.values())
                    final_payloads[user_id] = {
                        'notifications': unique_notifications,
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

        # =========================================================================
        # 1. SELF-HEALING & MERGE LOGIC (Existing)
        # =========================================================================
        if room.room_id.startswith("PENDING_DISCOVERY") and new_tracker_data.get('room_link'):
            real_uuid = _extract_ap_room_id(new_tracker_data['room_link'])
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
                    
                    for p_sub in pending_subs:
                        real_sub = session.query(UserRoomSubscription).filter_by(
                            user_id=p_sub.user_id, room_id=existing_real_room.id
                        ).first()
                        if not real_sub: p_sub.room_id = existing_real_room.id
                        else: session.delete(p_sub)
                    
                    for p_slot in pending_slots:
                        real_slot = session.query(UserTrackedSlot).filter_by(
                             user_id=p_slot.user_id, room_id=existing_real_room.id, slot_id=p_slot.slot_id
                        ).first()
                        if not real_slot: p_slot.room_id = existing_real_room.id
                        else: session.delete(p_slot)

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
        
        try:
            clean_time = remote_updated_at
            if '.' in clean_time:
                main, frac = clean_time.split('.')
                clean_time = f"{main}.{frac[:6]}"
            room.cheese_updated_at = datetime.fromisoformat(clean_time.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            room.cheese_updated_at = datetime.utcnow()

        # =========================================================================
        # 3. UNCLAIM SYNC (State-Based)
        # =========================================================================
        # Instead of looking at history, we look at the CURRENT database state.
        # IF a user is tracking a slot locally
        # AND they are a known Cheese User (have a cheese_user_id)
        # AND Cheese says "This slot is NOT owned by that ID"
        # THEN -> Delete the local tracking.

        # Map Position -> Game Data from Cheese
        new_games_map = {g['position']: g for g in new_tracker_data.get('games', [])}
        
        # Fetch all local tracking rows for this room
        # We join subscription -> user so we can check the cheese_user_id
        
        # Fetch all local tracking rows for this room
        current_tracked_slots = session.query(UserTrackedSlot).options(
            selectinload(UserTrackedSlot.user) 
        ).filter_by(room_id=room.id).all()

        for ts in current_tracked_slots:
            user = ts.user 
            
            if not user or not user.cheese_user_id:
                continue

            game_data = new_games_map.get(ts.slot_id)
            
            if game_data:
                # Case A: Slot exists in Cheese data. Check ownership.
                remote_owner_id = game_data.get('claimed_by_ct_user_id')
                if remote_owner_id != user.cheese_user_id:
                    logging.info(f"[POLLER_SYNC] Untracking Slot {ts.slot_id} (Owner mismatch: {remote_owner_id} != {user.cheese_user_id})")
                    session.delete(ts)
            else:
                # Case B: Slot is MISSING from Cheese data.
                # As per your finding: this implies it is Unclaimed/Hidden.
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
    
    room_data = await loop.run_in_executor(None, db_read_room_poll_state, db_id)
    if not room_data: return
        
    tracker_id = room_data['tracker_id']
    room_uuid = room_data['room_uuid']

    if not tracker_id: return

    tracker_data = await fetch_json(f"https://{hostname}/api/tracker/{tracker_id}")

    try:
        notifications_to_send = await loop.run_in_executor(
            None, db_process_poll_data, db_id, room_uuid, tracker_data, room_data 
        )
        
        if notifications_to_send:
            for user_id, data in notifications_to_send.items():
                logging.info(f"[NOTIFY] Sending {len(data['notifications'])} notification(s) to user {user_id}")
                await send_push_notifications(data['notifications'], data['tokens'], loop)

    except Exception as e:
        logging.error(f"[POLLER_ERROR][RoomDBID:{db_id}] Error in run_room_poll!", exc_info=True)

# Add to poller.py

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
    new_data = await fetch_json(url)
    
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
            'is_complete_status': room.is_complete
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
                'is_finished': False
            })
        
        setup_data['cached_players_json'] = json.dumps(player_list)
        setup_data['cached_total_slots'] = len(player_list)
        setup_data['cached_full_address'] = f"{hostname}:{room_status.get('last_port', '')}"
        setup_data['last_api_check'] = datetime.utcnow()

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
            for game, entries in setup_data['datapackage_entries_by_game'].items():
                try:
                    session.bulk_save_objects(entries)
                    session.commit()
                except IntegrityError:
                    session.rollback() 
                except Exception:
                    session.rollback()
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
        
        if room.failed_poll_count >= 10:
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

async def setup_worker(setup_queue, setup_semaphore, loop):
    while True:
        try:
            room_info = await setup_queue.get()
            async with setup_semaphore:
                await run_room_setup(room_info, loop)
            setup_queue.task_done()
        except Exception as e:
            logging.error(f"[SETUP_WORKER_ERROR] Unhandled error: {e}", exc_info=True)

async def poller_supervisor(app, loop):
    logging.info("[POLLER] Background polling service starting...")
    running_tasks = {}
    last_cleanup_time = datetime.utcnow()

    setup_queue = asyncio.Queue()
    setup_semaphore = asyncio.Semaphore(2) 
    
    asyncio.create_task(setup_worker(setup_queue, setup_semaphore, loop))
    asyncio.create_task(setup_worker(setup_queue, setup_semaphore, loop))
    
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
                        if room.id not in running_tasks:
                            logging.info(f"[SUPERVISOR] Queuing room {room.id} for setup.")
                            await setup_queue.put(room_info)
                        else:
                            logging.info(f"[SUPERVISOR] Re-queuing running room {room.id} for metadata repair.")
                            await setup_queue.put(room_info)
                    else:
                        if room.id not in running_tasks:
                            logging.info(f"[SUPERVISOR] Starting AP poller for room {room.id}")
                            task = asyncio.create_task(poll_room_with_interval(room_info, loop))
                            running_tasks[room.id] = task
                
                # --- 2. Cheese Task ---
                # We run this regardless of AP status (even if Pending!)
                cheese_task_key = f"cheese_{room.id}"
                
                if room.cheese_tracker_id:
                    if cheese_task_key not in running_tasks:
                        logging.info(f"[SUPERVISOR] Starting Cheese poller for room {room.id}")
                        c_task = asyncio.create_task(poll_cheese_with_interval(room_info, loop))
                        running_tasks[cheese_task_key] = c_task
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
                await loop.run_in_executor(None, db_run_cleanup)
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