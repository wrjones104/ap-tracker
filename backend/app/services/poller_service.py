import logging
import asyncio
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from app.utils import fetch_json_with_status, fetch_json, get_cheese_headers, db_suspend_room
from app.services.cheese_service import process_cheese_update
from app.services.notification_service import send_fcm_notifications

AP_POLL_SEMAPHORE_LIMIT = 5
CHEESE_POLL_SEMAPHORE_LIMIT = 3
ap_poll_semaphore = asyncio.Semaphore(AP_POLL_SEMAPHORE_LIMIT)
cheese_semaphore = asyncio.Semaphore(CHEESE_POLL_SEMAPHORE_LIMIT)
SEMAPHORE_WAIT_WARNING_THRESHOLD = 60

async def run_room_poll(room_info, loop, db_read_room_poll_state_fn, db_process_poll_data_fn):
    """
    Executes a stateless HTTP GET poll for an Archipelago room, using gatekeeper
    timestamp checks to skip redundant tracker downloads.
    """
    db_id = room_info['db_id']
    hostname = room_info['hostname']
    
    room_data = await loop.run_in_executor(None, db_read_room_poll_state_fn, db_id)
    if not room_data:
        return
        
    tracker_id = room_data['tracker_id']
    room_uuid = room_data['room_uuid']
    last_known_activity = room_data['last_remote_activity']
    cached_address = room_data.get('cached_full_address')
    needs_backfill = room_data.get('needs_backfill', False)

    if not tracker_id:
        return

    # GATEKEEPER CHECK: `/api/room_status/<room_uuid>`
    status_url = f"https://{hostname}/api/room_status/{room_uuid}"
    status_data, status_code = await fetch_json_with_status(status_url)

    current_remote_activity = None
    new_full_address = None
    should_fetch_tracker = True

    if status_code == 404:
        await loop.run_in_executor(None, db_suspend_room, db_id, "404 Not Found (Gatekeeper)")
        return

    if status_data:
        should_fetch_tracker = False
        
        remote_tracker_id = status_data.get('tracker')
        if remote_tracker_id and remote_tracker_id != tracker_id:
            logging.info(f"[POLLER_GATE] Tracker ID mismatch for room {db_id}. Forcing poll.")
            should_fetch_tracker = True

        remote_port = status_data.get('last_port')
        if remote_port:
            check_address = f"{hostname}:{remote_port}"
            if check_address != cached_address:
                logging.info(f"[POLLER_GATE] Port changed for Room {db_id} ({cached_address} -> {check_address}). Forcing poll.")
                new_full_address = check_address
                should_fetch_tracker = True

        remote_activity_str = status_data.get('last_activity')
        if remote_activity_str:
            try:
                dt_aware = parsedate_to_datetime(remote_activity_str)
                current_remote_activity = dt_aware.astimezone(timezone.utc).replace(tzinfo=None)
                if not last_known_activity or current_remote_activity > last_known_activity:
                    should_fetch_tracker = True
            except Exception as e:
                logging.warning(f"[POLLER_GATE] Date parse error for room {db_id}: {e}")
                should_fetch_tracker = True
        else:
            should_fetch_tracker = True

    if needs_backfill:
        logging.info(f"[POLLER_GATE] needs_backfill detected for Room {db_id}. Forcing poll.")
        should_fetch_tracker = True

    if not should_fetch_tracker:
        return

    start_wait_time = time.time()
    async with ap_poll_semaphore:
        wait_duration = time.time() - start_wait_time
        if wait_duration > SEMAPHORE_WAIT_WARNING_THRESHOLD:
            logging.warning(f"[HIGH_LOAD] Room {db_id} waited {wait_duration:.2f}s for semaphore.")
            
        tracker_data = await fetch_json(f"https://{hostname}/api/tracker/{tracker_id}")

    if not tracker_data:
        return

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

    try:
        notifications_to_send = await loop.run_in_executor(
            None, 
            db_process_poll_data_fn, 
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
                send_fcm_notifications(data['tokens'], data['notifications'])

    except Exception as e:
        logging.error(f"[POLLER_ERROR][RoomDBID:{db_id}] Error in run_room_poll: {e}", exc_info=True)
