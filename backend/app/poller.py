import asyncio
import logging
import aiohttp
import json
import websockets
import traceback
from datetime import datetime, timezone, timedelta
from threading import local
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import OperationalError, IntegrityError


from . import Session, get_firebase_app, process
from .models import (
    Device, TrackedRoom, UserRoomSubscription, UserTrackedSlot,
    DatapackageCache, NotifiedItem, NotifiedHint
)

from . import POLLING_INTERVAL_SECONDS, SUPERVISOR_INTERVAL_SECONDS

thread_local_data = local()

async def close_aiohttp_session():
    session = getattr(thread_local_data, "aiohttp_session", None)
    if session:
        await session.close()
        print("[POLLER] Aiohttp session closed.")

def get_aiohttp_session():
    if not hasattr(thread_local_data, "aiohttp_session"):
        thread_local_data.aiohttp_session = aiohttp.ClientSession()
    return thread_local_data.aiohttp_session

def log_resource_usage(app):
    """Logs the current CPU and Memory usage of this script."""
    if not app.config.get('DEBUG'): return
    cpu_usage = process.cpu_percent(interval=None)
    memory_info = process.memory_info()
    memory_mb = memory_info.rss / (1024 * 1024)
    print(f"[RESOURCES] CPU: {cpu_usage:.2f}% | Memory: {memory_mb:.2f} MB")

async def send_push_notifications(notifications, device_tokens):
    firebase_app = get_firebase_app()
    if not firebase_app or not notifications or not device_tokens: return

    from firebase_admin import messaging

    messages = []
    for content in notifications:
        try:
            logging.warning(f"[NOTIFIER] Preparing notification for {len(device_tokens)} devices. Title: {content['title']} | Body: {content['body']}")
        except Exception as e:
            logging.error(f"[NOTIFIER] Error creating log message: {e}")
        for token in device_tokens:
            android_config = messaging.AndroidConfig(priority='high')
            messages.append(messaging.Message(
                notification=messaging.Notification(title=content['title'], body=content['body']),
                token=token, android=android_config
            ))
    if not messages: return

    loop = asyncio.get_running_loop()
    for i in range(0, len(messages), 10):
        chunk = messages[i:i + 10]
        try:
            print(f"[FCM] Sending a chunk of {len(chunk)} messages...")
            response = await loop.run_in_executor(None, lambda: messaging.send_each(chunk))
            
            unregistered_tokens = []
            for idx, res in enumerate(response.responses):
                if not res.success:
                    error_code = res.exception.code if hasattr(res.exception, 'code') else "UNKNOWN"
                    if error_code in ['UNREGISTERED', 'NOT_FOUND']:
                        unregistered_tokens.append(chunk[idx].token)

            if unregistered_tokens:
                print(f"[FCM] Found {len(unregistered_tokens)} invalid devices. Removing from DB.")
                session = Session()
                session.query(Device).filter(Device.fcm_token.in_(unregistered_tokens)).delete(synchronize_session=False)
                session.commit()
                Session.remove()
        except Exception as e:
            print(f"[FCM] A critical error occurred while sending a chunk: {e}")
        if i + 10 < len(messages):
            await asyncio.sleep(1)

async def fetch_json(url):
    session = get_aiohttp_session()
    try:
        async with session.get(url, timeout=15) as response:
            response.raise_for_status()
            return await response.json()
    except Exception as e:
        return None

async def poll_room_instance(room_info):
    """
    Refactored version: Separates slow network I/O from the database transaction
    to prevent "database is locked" errors during room setup.
    
    (Version 3: Now includes hint suppression logic)
    """
    db_id = room_info['db_id']
    hostname = room_info['hostname']
    
    # --- STEP 1: Initial Read ---
    # We do a quick, separate read to get the room's current state.
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=db_id).options(selectinload('*')).first()
        if not room:
            print(f"[POLLER][RoomDBID:{db_id}] Room not found.")
            return

        # Load all needed attributes into local variables upfront
        room_uuid = room.room_id
        tracker_id = room.tracker_id
        cached_players_json_str = room.cached_players_json
        game_checksums_json_str = room.game_checksums_json
        is_complete_status = room.is_complete
    finally:
        Session.remove() # Close the session immediately after reading.

    # --- STEP 2: Network I/O (No DB Session Open) ---
    # All slow network operations happen here, while the DB is unlocked.
    
    setup_data = {} # Will hold all data we need to commit
    
    if not tracker_id or not game_checksums_json_str or game_checksums_json_str == '{}':
        print(f"[POLLER_SETUP][RoomDBID:{db_id}] Tracker ID or checksums missing, running setup...")
        try:
            room_status = await fetch_json(f"https://{hostname}/api/room_status/{room_uuid}")
            if not room_status:
                print(f"[POLLER_SETUP_ERROR][RoomDBID:{db_id}] Failed to fetch room status.")
                return

            # Process player data into memory
            players_raw = room_status.get('players', [])
            player_list = [{'slot_id': i + 1, 'name': p[0], 'game': p[1]} for i, p in enumerate(players_raw)]
            setup_data['cached_players_json'] = json.dumps(player_list)
            setup_data['cached_total_slots'] = len(player_list)
            setup_data['cached_full_address'] = f"{hostname}:{room_status.get('last_port', '')}"
            setup_data['last_api_check'] = datetime.utcnow()

            new_tracker_id = room_status.get('tracker')
            if not new_tracker_id:
                print(f"[POLLER_SETUP_WARN][RoomDBID:{db_id}] No tracker ID found in status. Will retry.")
            else:
                if not tracker_id:
                    setup_data['tracker_id'] = new_tracker_id
                    tracker_id = new_tracker_id # Update local var for main poll

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
                    print(f"[POLLER_SETUP_WARN][RoomDBID:{db_id}] Failed to get checksums from WebSocket: {ws_e}")
                    checksums = room_status.get('datapackage_checksums', {})
            else:
                checksums = room_status.get('datapackage_checksums', {})

            new_checksums_json_str = json.dumps(checksums)
            datapackage_entries_to_add = []

            if checksums and new_checksums_json_str != game_checksums_json_str:
                print(f"[POLLER_SETUP_DEBUG][RoomDBID:{db_id}] New/updated checksums found. Fetching datapackages...")
                
                # We need a *temporary* session just to read the cache
                temp_session = Session()
                existing_checksums = set(c[0] for c in temp_session.query(DatapackageCache.checksum).distinct())
                Session.remove()

                for game, checksum in checksums.items():
                    if checksum not in existing_checksums:
                        game_data = await fetch_json(f"https://{hostname}/api/datapackage/{checksum}")
                        if not game_data: continue
                        
                        actual_data = game_data.get('games', {}).get(game, game_data)
                        for n, eid in actual_data.get('item_name_to_id', {}).items():
                            datapackage_entries_to_add.append(DatapackageCache(game=game, checksum=checksum, entity_type='item', entity_id=eid, entity_name=n))
                        for n, eid in actual_data.get('location_name_to_id', {}).items():
                            datapackage_entries_to_add.append(DatapackageCache(game=game, checksum=checksum, entity_type='location', entity_id=eid, entity_name=n))
                
                if datapackage_entries_to_add:
                    setup_data['datapackage_entries'] = datapackage_entries_to_add
                
                setup_data['game_checksums_json'] = new_checksums_json_str
                game_checksums_json_str = new_checksums_json_str # Update local var

            # Store all gathered data
            setup_data['is_setup'] = True
            print(f"[POLLER_SETUP][RoomDBID:{db_id}] Setup network fetch complete.")

        except Exception as e:
            print(f"[POLLER_SETUP_ERROR][RoomDBID:{db_id}] Unhandled setup network error: {e}")
            traceback.print_exc()
            return # Exit if network setup fails

    # --- STEP 3: Database Transaction ---
    # Now, we open a *new* session to commit all our in-memory data.
    # This block is wrapped in the lock-handling logic.
    session = Session()
    try:
        # Re-fetch the room object *within this new session*
        room = session.query(TrackedRoom).filter_by(id=db_id).first()
        if not room: return # Should not happen, but good to check

        # Apply all setup data from memory
        if setup_data.get('is_setup'):
            if 'cached_players_json' in setup_data:
                room.cached_players_json = setup_data['cached_players_json']
                cached_players_json_str = setup_data['cached_players_json'] # Update local var
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
            
            if setup_data.get('datapackage_entries'):
                try:
                    session.bulk_save_objects(setup_data['datapackage_entries'])
                    print(f"[POLLER_SETUP_DEBUG][RoomDBID:{db_id}] Saved {len(setup_data['datapackage_entries'])} new datapackage entries.")
                except IntegrityError:
                    session.rollback() # Handle race condition
                    print(f"[POLLER_SETUP_WARN][RoomDBID:{db_id}] Datapackage race condition occurred. Safe to ignore.")
                
            session.commit() # Commit all setup changes
            print(f"[POLLER_SETUP][RoomDBID:{db_id}] Setup data committed to DB.")


        # --- Main Polling Logic ---
        if not tracker_id:
            print(f"[POLLER_WARN][RoomDBID:{db_id}] No tracker_id, cannot poll. Will retry setup.")
            return

        # Network call happens *before* most DB writes
        tracker_data = await fetch_json(f"https://{hostname}/api/tracker/{tracker_id}")

        if not tracker_data:
            room.failed_poll_count += 1
            if room.failed_poll_count >= 20: room.is_suspended = True
            session.commit()
            return

        room.failed_poll_count = 0
        room.last_successful_poll = datetime.utcnow()
        
        # Ensure local variables have the latest data
        players = json.loads(cached_players_json_str if cached_players_json_str else '[]')
        game_checksums = json.loads(game_checksums_json_str if game_checksums_json_str else '{}')
        name_map = {p['slot_id']: p['name'] for p in players}
        game_map = {p['slot_id']: p['game'] for p in players}

        # --- "INTELLIGENCE" CHECK ---
        has_item_history = session.query(NotifiedItem.id).filter_by(room_id=room_uuid).limit(1).scalar() is not None
        has_hint_history = session.query(NotifiedHint.id).filter_by(room_id=room_uuid).limit(1).scalar() is not None

        # --- PERFORMANCE FIX (Load existing DB items/hints into sets) ---
        existing_items_in_db = set(session.query(NotifiedItem.receiving_slot_id, NotifiedItem.item_id, NotifiedItem.location_id).filter_by(room_id=room_uuid))
        existing_hints_in_db = set(session.query(NotifiedHint.item_owner_id, NotifiedHint.location_owner_id, NotifiedHint.item_id, NotifiedHint.location_id).filter_by(room_id=room_uuid))

        tracked_slots_by_user = {}
        all_tracked_slots_query = session.query(UserTrackedSlot.user_id, UserTrackedSlot.slot_id).filter_by(room_id=db_id)
        for user_id, slot_id in all_tracked_slots_query:
            tracked_slots_by_user.setdefault(user_id, set()).add(slot_id)

        if not tracked_slots_by_user:
             session.commit() # Commit poll time update
             return

        aliases_by_user = { sub.user_id: sub.alias for sub in session.query(UserRoomSubscription).filter(UserRoomSubscription.user_id.in_(tracked_slots_by_user.keys()), UserRoomSubscription.room_id == db_id) }

        notifications_by_user = {}

        # Auto-untrack finished players
        player_statuses_raw = tracker_data.get('player_status', {})
        finished_player_ids = set()
        if isinstance(player_statuses_raw, dict): finished_player_ids = {int(p) for p, s in player_statuses_raw.items() if s == 30}
        elif isinstance(player_statuses_raw, list):
             for status_info in player_statuses_raw:
                 if isinstance(status_info, dict) and status_info.get('status') == 30 and 'player' in status_info:
                     finished_player_ids.add(status_info.get('player'))

        if finished_player_ids:
            players_to_untrack_by_user = {} # { user_id: [list of names] }

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
                    'title': f"潤 Player(s) Finished!",
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
                print(f"[POLLER_ACTION][RoomDBID:{db_id}] Automatically untracked {deleted_count} finished player(s).")

        # Check for full room completion
        total_players = len(players)
        # Use the local variable, but also update the DB object 'room'
        if total_players > 0 and len(finished_player_ids) >= total_players:
            if not is_complete_status: # Use local var for check
                room.is_complete = True # Update DB object
                print(f"[POLLER_ACTION][RoomDBID:{db_id}] Room marked as complete.")
            is_complete_status = True # Update local var

        events_to_log = []
        items_to_add_to_db = []
        hints_to_add_to_db = []
        items_in_this_batch = set()
        hints_in_this_batch = set()

        # --- ITEM PROCESSING with FLAGS ---
        items_processed_count = 0
        items_skipped_classification = 0
        items_skipped_duplicate = 0
        items_added_count = 0
        added_items_details = [] 

        for p_items in tracker_data.get('player_items_received', []):
            rid = p_items.get('player') # receiver_id
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
                    item_id, loc_id, _, flags = item_tuple_data 
                except (ValueError, TypeError, IndexError) as e:
                    print(f"[POLLER_WARN][RoomDBID:{db_id}] Error unpacking item tuple: {item_tuple_data} | Error: {e}")
                    continue 

                item_key_db = (rid, item_id, loc_id)
                item_key_batch = (room_uuid, rid, item_id, loc_id) 

                if (item_key_db in existing_items_in_db) or (item_key_batch in items_in_this_batch):
                    items_skipped_duplicate += 1
                    continue

                if not (flags & 1 or flags & 2): # Check for Progression (1) or Useful (2)
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

                    item_name = session.query(DatapackageCache.entity_name).filter_by(
                        game=receiver_game,
                        checksum=game_checksum,
                        entity_type='item',
                        entity_id=item_id
                    ).scalar() or f"ID {item_id}"

                    for user_id, tracked_slots in tracked_slots_by_user.items():
                        if rid in tracked_slots:
                            alias = aliases_by_user.get(user_id, "Unknown Room")
                            
                            # --- ITEM SUPPRESSION LOGIC ---
                            user_slot_query = session.query(UserTrackedSlot.added_at).filter_by(
                                user_id=user_id, room_id=db_id, slot_id=rid
                            ).scalar()
                            
                            if user_slot_query and datetime.utcnow() - user_slot_query < timedelta(minutes=2):
                                logging.warning(f"[NOTIFY_SKIP][RoomDBID:{db_id}] User {user_id} is tracking Slot {rid}, but it was added at {user_slot_query}. Suppressing notification for item {item_id}.")
                                continue 
                            # --- END SUPPRESSION LOGIC ---

                            is_progression = bool(flags & 1)
                            
                            if is_progression:
                                title = f"笨ｨ {item_name}"
                                item_type = "item_progression"
                            else: # It must be Useful if it's not Progression
                                title = f"総 {item_name}"
                                item_type = "item_useful"

                            notifications_by_user.setdefault(user_id, []).append({
                                'title': title,
                                'body': f"Received by {name_map.get(rid, f'P{rid}')} in '{alias}'",
                                'type': item_type,
                                'details': item_key_batch
                                })
                else:
                    logging.warning(f"[NOTIFY_SKIP][RoomDBID:{db_id}] 'has_item_history' is False. Suppressing notification for item {item_id} (Slot {rid}) during initial backfill.")

        if items_processed_count > 0: 
             added_items_log_str = ", ".join(added_items_details) if added_items_details else "None"
             print(f"[POLLER_DEBUG][RoomDBID:{db_id}] Item Stats: Processed={items_processed_count}, Skipped (Class)={items_skipped_classification}, Skipped (Dupe)={items_skipped_duplicate}, Added={items_added_count} | New Items: [{added_items_log_str}]")

        # --- HINT PROCESSING ---
        hints_processed_count = 0
        hints_added_count = 0
        for p_hints in tracker_data.get('hints', []):
             for hint_data in p_hints.get('hints', []):
                 hints_processed_count += 1
                 try:
                     io_id, lo_id, loc_id, item_id, *_ = hint_data
                 except ValueError:
                     continue 

                 hint_key_db = (io_id, lo_id, item_id, loc_id)
                 hint_key_batch = (room_uuid, io_id, lo_id, item_id, loc_id)

                 if (hint_key_db in existing_hints_in_db) or (hint_key_batch in hints_in_this_batch):
                     continue

                 hints_to_add_to_db.append(NotifiedHint(room_id=hint_key_batch[0], item_owner_id=hint_key_batch[1], location_owner_id=hint_key_batch[2], item_id=hint_key_batch[3], location_id=hint_key_batch[4]))
                 hints_in_this_batch.add(hint_key_batch)
                 hints_added_count += 1

                 for user_id, tracked_slots in tracked_slots_by_user.items():
                     is_for_us, is_at_our_location = io_id in tracked_slots, lo_id in tracked_slots
                     if is_for_us or is_at_our_location:
                         
                         # --- NEW HINT SUPPRESSION LOGIC ---
                         # We check the timestamp of whichever slot triggered this notification (io_id or lo_id)
                         slot_to_check = io_id if is_for_us else lo_id
                         
                         user_slot_query = session.query(UserTrackedSlot.added_at).filter_by(
                             user_id=user_id, room_id=db_id, slot_id=slot_to_check
                         ).scalar()

                         if user_slot_query and datetime.utcnow() - user_slot_query < timedelta(minutes=2):
                             logging.warning(f"[NOTIFY_SKIP][RoomDBID:{db_id}] User {user_id} is tracking Slot {slot_to_check}, but it was added at {user_slot_query}. Suppressing hint notification.")
                             continue
                         # --- END NEW HINT SUPPRESSION LOGIC ---

                         io_game, lo_game = game_map.get(io_id, "Unknown"), game_map.get(lo_id, "Unknown")
                         item_name = session.query(DatapackageCache.entity_name).filter_by(game=io_game, checksum=game_checksums.get(io_game), entity_type='item', entity_id=item_id).scalar() or f"ID {item_id}"
                         loc_name = session.query(DatapackageCache.entity_name).filter_by(game=lo_game, checksum=game_checksums.get(lo_game), entity_type='location', entity_id=loc_id).scalar() or f"ID {loc_id}"
                         alias = aliases_by_user.get(user_id, "Unknown Room")
                         title, body = "", ""

                         if is_for_us:
                             title = f"剥 Hint for your {item_name}!"
                             body = f"It's at {name_map.get(lo_id, f'P{lo_id}')}'s location: '{loc_name}' in '{alias}'"
                         elif is_at_our_location:
                             title = f"剥 Item at your location!"
                             body = f"{name_map.get(io_id, f'P{io_id}')}'s {item_name} is at your location: '{loc_name}' in '{alias}'"

                         notifications_by_user.setdefault(user_id, []).append({'title': title, 'body': body, 'type': 'hint', 'details': hint_key_batch})

        if hints_processed_count > 0:
             print(f"[POLLER_DEBUG][RoomDBID:{db_id}] Hint Stats: Processed={hints_processed_count}, Added={hints_added_count}")

        # Send notifications
        if notifications_by_user:
            all_user_ids = notifications_by_user.keys()
            devices_to_notify = session.query(Device).filter(Device.user_id.in_(all_user_ids)).all()
            tokens_by_user = {}
            for device in devices_to_notify: tokens_by_user.setdefault(device.user_id, []).append(device.fcm_token)

            for user_id, notifications in notifications_by_user.items():
                user_tokens = tokens_by_user.get(user_id)
                if user_tokens:
                    print(f"[NOTIFY] Sending {len(notifications)} notification(s) to user {user_id} for room '{aliases_by_user.get(user_id)}'")
                    unique_notifications = list({json.dumps(d): d for d in notifications}.values())
                    await send_push_notifications(unique_notifications, user_tokens)
                    for n in unique_notifications: events_to_log.append(n)
                else:
                    logging.warning(f"[NOTIFY_SKIP][RoomDBID:{db_id}] User {user_id} had {len(notifications)} notifications queued, but has NO registered device tokens.")

        else:
            if items_added_count > 0:
                logging.warning(f"[NOTIFY_SKIP][RoomDBID:{db_id}] Added {items_added_count} new items, but no notifications were queued (e.g., all suppressed or no users tracking).")

        if items_to_add_to_db:
            session.bulk_save_objects(items_to_add_to_db)
            if not has_item_history:
                print(f"[POLLER][RoomDBID:{db_id}] Silently backfilled {len(items_to_add_to_db)} historical items (Progression/Useful).")
            elif not notifications_by_user: 
                print(f"[POLLER][RoomDBID:{db_id}] Silently added {len(items_to_add_to_db)} new items (Progression/Useful).")

        if hints_to_add_to_db:
            session.bulk_save_objects(hints_to_add_to_db)
            if not has_hint_history:
                print(f"[POLLER][RoomDBID:{db_id}] Silently backfilled {len(hints_to_add_to_db)} historical hints.")
            elif not notifications_by_user: 
                 print(f"[POLLER][RoomDBID:{db_id}] Silently added {len(hints_to_add_to_db)} new hints.")

        # Final single commit
        session.commit()

    except OperationalError as oe: 
        print(f"[POLLER_ERROR][RoomDBID:{db_id}] Database was locked during main poll. Skipping cycle. Error: {oe}")
        session.rollback()
    except Exception as e:
        print(f"[POLLER_ERROR][RoomDBID:{db_id}] An unhandled exception occurred in main poll loop!")
        traceback.print_exc()
        session.rollback()

    finally:
        Session.remove()

async def poll_room_with_interval(room_info):
    """
    Wrapper that calls the main polling logic at a regular interval.
    This replaces the old version.
    """
    while True:
        try:
            await poll_room_instance(room_info)
        except asyncio.CancelledError:
            break
        except Exception as e:
            db_id = room_info.get('db_id', 'Unknown')
            print(f"[POLLER_ERROR][RoomDBID:{db_id}] Unhandled error: {e}")
        await asyncio.sleep(POLLING_INTERVAL_SECONDS)

async def poller_supervisor(app):
    """
    The main supervisor loop for the background poller.
    - Manages which rooms are actively being polled.
    - Starts/stops polling tasks based on room status (is_suspended, is_complete).
    - Periodically cleans up old, un-subscribed rooms.
    """
    print("[POLLER] Background polling service starting...")
    running_tasks = {}
    last_cleanup_time = datetime.utcnow()

    while True:
        session = Session()
        try:
            log_resource_usage(app)

            active_rooms_in_db = session.query(TrackedRoom).filter(
                TrackedRoom.is_complete == False,
                TrackedRoom.is_suspended == False
            ).all()
            
            current_active_room_ids = {room.id for room in active_rooms_in_db}
            
            for room in active_rooms_in_db:
                if room.id not in running_tasks:
                    print(f"[SUPERVISOR] Starting poller for room ID: {room.id} ({room.room_id})")
                    room_info = {'db_id': room.id, 'hostname': room.hostname, 'room_uuid': room.room_id}
                    task = asyncio.create_task(poll_room_with_interval(room_info))
                    running_tasks[room.id] = task

            inactive_room_ids = set(running_tasks.keys()) - current_active_room_ids
            for room_id in inactive_room_ids:
                print(f"[SUPERVISOR] Room ID {room_id} is no longer active. Stopping poller.")
                task_to_stop = running_tasks.pop(room_id, None)
                if task_to_stop:
                    task_to_stop.cancel()

            if datetime.utcnow() - last_cleanup_time > timedelta(hours=24):
                print("[JANITOR] Running daily cleanup of old, un-subscribed rooms...")
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
                        print(f"[JANITOR] Deleting abandoned room {room.room_id}")
                        session.delete(room)
                    session.commit()
                else:
                    print("[JANITOR] No abandoned rooms to delete.")
                
                last_cleanup_time = datetime.utcnow()

        except Exception as e:
            print(f"[SUPERVISOR] An unhandled error occurred: {e}")
        finally:
            Session.remove()

        await asyncio.sleep(SUPERVISOR_INTERVAL_SECONDS)

def run_poller(app):
    """The entry point for the poller thread."""
    asyncio.run(poller_supervisor(app))