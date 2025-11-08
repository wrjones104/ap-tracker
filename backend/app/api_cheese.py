import logging
import requests
import threading
import os
import json
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from datetime import datetime, timedelta

from . import Session
from .models import User, TrackedRoom, UserRoomSubscription, UserTrackedSlot
from .api import token_required, log_api_call, handle_db_errors
from .encryption import encrypt_api_key, decrypt_api_key

load_dotenv()

bp = Blueprint('api_cheese', __name__)

CHEESE_BASE_URL = os.environ.get('CHEESE_BASE_URL', 'https://cheesetrackers.theincrediblewheelofchee.se/api')

def _sync_rooms_from_cheese_tracker_task(user_id):
    """
    (V5 Refactored) Runs the full sync.
    Fixes the lock by doing all network calls *before* the transaction.
    """
    
    # === 1. PRE-FLIGHT: Get User and Headers ===
    # Use a *temporary* session just to get the API key and info.
    # We do not hold this session or a lock.
    temp_session = Session()
    user_for_key = None
    api_key = None
    discord_username = None
    
    try:
        user_for_key = temp_session.query(User).filter_by(id=user_id).first()
        if not user_for_key or not user_for_key.cheese_api_key:
            logging.debug(f"[CHEESE_SYNC_BG] Aborting: No user or key for {user_id}")
            return
            
        api_key = decrypt_api_key(user_for_key.cheese_api_key)
        if not api_key:
            logging.error(f"[CHEESE_SYNC_BG] Failed to decrypt API key for user {user_id}. Aborting sync.")
            return
        discord_username = user_for_key.discord_username
    finally:
        Session.remove() # Close the temp session

    headers = {"Authorization": f"Bearer {api_key}"}
    
    # === 2. NETWORK PHASE: No DB session open! ===
    cheese_trackers = []
    tracker_details_map = {}
    try:
        logging.debug(f"[CHEESE_SYNC_BG] User {user_id}: Starting network phase.")
        # 1. Fetch Dashboard
        resp = requests.get(f"{CHEESE_BASE_URL}/dashboard/tracker", headers=headers, timeout=10)
        resp.raise_for_status()
        cheese_trackers = resp.json()
        
        # 2. Fetch ALL details
        for ct_data in cheese_trackers:
            tracker_id = ct_data.get('tracker_id')
            if not tracker_id: continue
            
            try:
                detail_resp = requests.get(f"{CHEESE_BASE_URL}/tracker/{tracker_id}", headers=headers, timeout=15)
                if detail_resp.ok:
                    tracker_details_map[tracker_id] = detail_resp.json()
            except requests.exceptions.ReadTimeout:
                logging.error(f"[CHEESE_DEEP_SYNC] Timeout getting details for tracker {tracker_id}. Skipping.")
            except Exception as e:
                logging.error(f"[CHEESE_DEEP_SYNC] Failed to fetch details for {tracker_id}: {e}")
                
        logging.debug(f"[CHEESE_SYNC_BG] User {user_id}: Network phase complete. Fetched {len(tracker_details_map)} details.")

    except Exception as e:
        logging.error(f"[CHEESE_SYNC_BG] FULL sync failed for user {user_id} in network phase: {e}", exc_info=True)
        return # Hard fail, can't proceed

    # === 3. DATABASE PHASE: Now we open the session and lock ===
    session = Session()
    try:
        now = datetime.utcnow()
        
        # Lock the user row
        user = session.query(User).filter_by(id=user_id).with_for_update().first()

        # Cooldown & Concurrency checks
        if user.cheese_last_sync and (now - user.cheese_last_sync) < timedelta(minutes=5):
             logging.debug(f"[CHEESE_SYNC_BG] Aborting: Sync for user {user_id} ran too recently.")
             session.commit() # Release lock
             return
        
        if user.is_syncing_cheese:
            if user.cheese_sync_started_at and (now - user.cheese_sync_started_at) > timedelta(minutes=15):
                logging.warning(f"[CHEESE_SYNC_BG] Found stale sync lock for user {user_id}. Taking over.")
            else:
                logging.debug(f"[CHEESE_SYNC_BG] Sync for user {user_id} already in progress. Skipping.")
                session.commit() # Release lock
                return

        # Take the lock
        user.is_syncing_cheese = True
        user.cheese_sync_started_at = now
        
        # This transaction is now FAST - no network calls
        stats = {'rooms_created': 0, 'subs_added': 0, 'slots_synced': 0}
        found_cheese_id = (user.cheese_user_id is not None)

        for ct_data in cheese_trackers:
            ap_room_id = None # Define here for error logging
            try:
                room_link = ct_data.get('room_link')
                tracker_id = ct_data.get('tracker_id')
                if not room_link or not tracker_id: continue

                try:
                    parsed_url = urlparse(room_link)
                    ap_room_id = parsed_url.path.split('/')[-1]
                    hostname = parsed_url.hostname
                    if not ap_room_id or not hostname: continue
                except Exception:
                    continue

                # 2. Find/Create Room
                local_room = session.query(TrackedRoom).filter_by(room_id=ap_room_id).first()
                if not local_room:
                    local_room = TrackedRoom(
                        room_id=ap_room_id, hostname=hostname, 
                        cheese_tracker_id=tracker_id, cached_full_address=hostname
                    )
                    session.add(local_room)
                    session.flush() # Need the ID for the subscription
                    stats['rooms_created'] += 1

                if local_room.cheese_tracker_id != tracker_id:
                     local_room.cheese_tracker_id = tracker_id

                # 3. Ensure Subscription
                sub = session.query(UserRoomSubscription).filter_by(user_id=user.id, room_id=local_room.id).first()
                if not sub:
                    alias_name = ct_data.get('title') or "No Name"
                    session.add(UserRoomSubscription(
                        user_id=user.id, room_id=local_room.id,
                        alias=alias_name, icon_name='cheese'
                    ))
                    stats['subs_added'] += 1

                # 4. DEEP SLOT SYNC (from in-memory data)
                details = tracker_details_map.get(tracker_id)
                if details:
                    games = details.get('games', []) 
                    slots_to_track_from_cheese = set()
                    
                    for game in games:
                        cheese_discord = game.get('effective_discord_username')
                        
                        if cheese_discord and discord_username and \
                           cheese_discord.lower() == discord_username.lower():
                            
                            ap_slot_id = game.get('position')
                            if ap_slot_id:
                                slots_to_track_from_cheese.add(ap_slot_id)
                            
                            if not found_cheese_id:
                                ct_id = game.get('claimed_by_ct_user_id')
                                if ct_id:
                                    logging.info(f"[CHEESE_SYNC_BG] Discovered Cheese User ID: {ct_id}")
                                    user.cheese_user_id = ct_id # Save it!
                                    found_cheese_id = True
                    
                    if slots_to_track_from_cheese:
                        existing_slots = session.query(UserTrackedSlot.slot_id).filter_by(
                            user_id=user.id, room_id=local_room.id
                        ).all()
                        existing_set = {s[0] for s in existing_slots}

                        to_add = slots_to_track_from_cheese - existing_set
                        for new_slot_id in to_add:
                            session.add(UserTrackedSlot(user_id=user.id, room_id=local_room.id, slot_id=new_slot_id))
                            stats['slots_synced'] += 1
                        
                        to_remove = existing_set - slots_to_track_from_cheese
                        if to_remove:
                            session.query(UserTrackedSlot).filter(
                                UserTrackedSlot.user_id == user.id,
                                UserTrackedSlot.room_id == local_room.id,
                                UserTrackedSlot.slot_id.in_(to_remove)
                            ).delete(synchronize_session=False)

            except Exception as e:
                # Log error for this specific room but continue the loop
                logging.error(f"[CHEESE_SYNC_BG] Failed to process room {ap_room_id or 'Unknown'}: {e}", exc_info=False)
                # We don't rollback, we just let the main transaction commit
                # whatever succeeded before this room.
        
        # Commit all successful rooms/slots/ID changes
        user.cheese_last_sync = datetime.utcnow()
        user.is_syncing_cheese = False
        user.cheese_sync_started_at = None
        session.commit()
        logging.info(f"[CHEESE_SYNC_BG] Sync for user {user_id} complete! {stats}")

    except Exception as e:
        # This catches a major error, like the DB locking failing
        session.rollback()
        logging.error(f"[CHEESE_SYNC_BG] FULL sync failed for user {user_id} in database phase: {e}", exc_info=True)
    finally:
        # --- UNLOCKING ---
        # We must release the lock, even if the sync failed
        # Use a *new* session in case the old one is poisoned
        try:
            lock_session = Session()
            lock_session.query(User).filter(User.id == user_id).update({
                'is_syncing_cheese': False,
                'is_syncing_cheese': False,
                'cheese_sync_started_at': None
            })
            lock_session.commit()
        except Exception as e:
            logging.error(f"Failed to release sync lock for user {user_id}: {e}")
            if lock_session:
                lock_session.rollback()
        finally:
            if 'lock_session' in locals() and lock_session:
                Session.remove()
            # Also remove the main session
            Session.remove()
        # --- END UNLOCKING ---


@bp.route('/auth', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def connect_cheese_account(current_user):
    """
    Sets the Cheese API key and triggers an *asynchronous* pull-sync.
    """
    data = request.json
    api_key = data.get('api_key')

    if not api_key or not isinstance(api_key, str) or len(api_key.strip()) == 0 or len(api_key) > 256:
        return jsonify({'error': 'Invalid or missing api_key.'}), 400

    api_key = api_key.strip()

    session = Session()
    user = session.merge(current_user)
    
    encrypted_key = encrypt_api_key(api_key)
    if not encrypted_key:
        return jsonify({'error': 'Failed to secure API key.'}), 500

    user.cheese_api_key = encrypted_key
    session.commit()

    # --- RUN SYNC IN BACKGROUND ---
    try:
        threading.Thread(
            target=_sync_rooms_from_cheese_tracker_task, 
            args=(user.id,)
        ).start()
    except Exception as e:
        logging.error(f"Failed to start sync thread for user {user.id}: {e}")
        
    return jsonify({
        'message': 'Connected! Syncing your rooms in the background. This may take a minute.', 
        'is_connected': True
    })

@bp.route('/auth', methods=['DELETE'])
@handle_db_errors
@log_api_call
@token_required
def disconnect_cheese_account(current_user):
    """
    Removes the Cheese API key, effectively disconnecting the integration.
    """
    session = Session()
    user = session.merge(current_user)
    user.cheese_api_key = None
    session.commit()
    return jsonify({'message': 'Disconnected from Cheese Tracker.'})

@bp.route('/sync', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def trigger_manual_sync(current_user):
    """
    Manually triggers an *asynchronous* pull-sync from Cheese Tracker.
    """
    if not current_user.cheese_api_key:
        return jsonify({'error': 'Not connected to Cheese Tracker.'}), 400

    try:
        threading.Thread(
            target=_sync_rooms_from_cheese_tracker_task, 
            args=(current_user.id,)
        ).start()
    except Exception as e:
        logging.error(f"Failed to start manual sync thread for user {current_user.id}: {e}")
        return jsonify({'error': 'Failed to start sync process.'}), 500
        
    return jsonify({'message': 'Sync started! Your rooms will update shortly.'})


def push_new_room_to_cheese(user_id, tracker_url, ap_room_id, room_url, alias):
    """
    (V4) Pushes a new room to Cheese Tracker.
    1. Creates the tracker via POST.
    2. Updates the tracker via PUT to add the room_link
       AND the title (but *only if* the title is currently blank).
    """
    session = Session()
    try:
        user = session.query(User).filter_by(id=user_id).first()
        if not user or not user.cheese_api_key:
            logging.warning(f"[CHEESE_PUSH_NEW] Aborting push for {tracker_url}: No API key.")
            return

        api_key = decrypt_api_key(user.cheese_api_key)
        if not api_key:
            logging.error(f"[CHEESE_PUSH_NEW] Failed to decrypt API key for user {user_id}. Aborting push.")
            return

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        
        # Step 1: POST to create/get the tracker
        payload = {"url": tracker_url}
        response_post = requests.post(f"{CHEESE_BASE_URL}/tracker", json=payload, headers=headers, timeout=10)

        if not (response_post.status_code == 200 or response_post.status_code == 201):
            logging.warning(f"[CHEESE_PUSH_NEW] Failed (POST) to create tracker for {tracker_url}: {response_post.status_code} {response_post.text}")
            return
            
        data = response_post.json()
        cheese_tracker_id = data.get('tracker_id')
        
        if not cheese_tracker_id:
            logging.error(f"[CHEESE_PUSH_NEW] Succeeded POST, but no tracker_id in response for {tracker_url}.")
            return

        # Step 2: GET the tracker's current state
        response_get = requests.get(f"{CHEESE_BASE_URL}/tracker/{cheese_tracker_id}", headers=headers, timeout=10)
        
        # This is the tracker's state *before* our update
        tracker_data = {}
        if response_get.ok:
            tracker_data = response_get.json()
        
        # Step 3: Create the PUT payload
        
        # --- THIS IS THE FIX ---
        # Get the title currently on Cheese
        current_title = tracker_data.get('title', '')
        
        # Only use our app's alias if the Cheese title is blank
        final_title = current_title if current_title else alias
        # --- END FIX ---
            
        put_payload = {
            "title": final_title, # Use our new conditional title
            "description": tracker_data.get('description', ''),
            "owner_ct_user_id": tracker_data.get('owner_ct_user_id'),
            "lock_settings": tracker_data.get('lock_settings', False),
            "global_ping_policy": tracker_data.get('global_ping_policy'),
            "room_link": room_url,
            "inactivity_threshold_yellow_hours": tracker_data.get('inactivity_threshold_yellow_hours', 24),
            "inactivity_threshold_red_hours": tracker_data.get('inactivity_threshold_red_hours', 48),
            "require_authentication_to_claim": tracker_data.get('require_authentication_to_claim', False)
        }
        
        # 4. Create PUT headers with the timestamp
        put_headers = headers.copy()
        # Use the timestamp *only if* we were able to fetch the tracker data
        if 'updated_at' in tracker_data:
            put_headers['If-Unmodified-Since'] = tracker_data.get('updated_at')
        
        # 5. PUT the update
        response_put = requests.put(f"{CHEESE_BASE_URL}/tracker/{cheese_tracker_id}", json=put_payload, headers=put_headers, timeout=10)
        
        if not (response_put.status_code == 200 or response_put.status_code == 204):
            # This might fail with a 428 if our GET failed, which is okay.
            # The main goal was the POST.
            logging.warning(f"[CHEESE_PUSH_NEW] Failed (PUT) to update title/room_link for {cheese_tracker_id}: {response_put.status_code} {response_put.text}")
        
        # 6. Save the new ID to our local DB
        local_room = session.query(TrackedRoom).filter_by(room_id=ap_room_id).first()
        if local_room:
            local_room.cheese_tracker_id = cheese_tracker_id
            session.commit()
            logging.info(f"[CHEESE_PUSH_NEW] Successfully created/linked {ap_room_id} to Cheese ID {cheese_tracker_id}.")
        else:
            logging.error(f"[CHEESE_PUSH_NEW] Race condition: Could not find local room {ap_room_id} to link.")

    except Exception as e:
        session.rollback()
        logging.error(f"[CHEESE_PUSH_NEW] Error pushing new room: {e}", exc_info=True)
    finally:
        Session.remove()

def push_slot_changes_to_cheese(session, user, room_db_id, added_slots, removed_slots):
    """
    (FIXED V12) Pushes changes to Cheese Tracker.
    Learns the cheese_user_id on the first push if unknown.
    """
    api_key = decrypt_api_key(user.cheese_api_key)
    if not api_key:
        logging.warning("[CHEESE_PUSH] Aborting: Could not decrypt API key.")
        return

    local_room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
    if not local_room or not local_room.cheese_tracker_id:
        return

    base_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    tracker_id = local_room.cheese_tracker_id
    
    # We pass the full user object to the thread now
    
    # Helper function to send the state
    def send_state(ap_position, is_tracked, current_user_id):
        # The thread will create its *own* session
        thread_session = Session()
        try:
            # Re-fetch the user *inside the thread* to be safe
            thread_user = thread_session.query(User).filter_by(id=current_user_id).first()
            if not thread_user: return

            my_ct_id = thread_user.cheese_user_id # Get the most up-to-date ID

            # 1. FETCH LATEST STATE
            detail_resp = requests.get(f"{CHEESE_BASE_URL}/tracker/{tracker_id}", headers=base_headers, timeout=10)
            if not detail_resp.ok:
                logging.warning(f"[CHEESE_PUSH] Failed to fetch details for {tracker_id} before push.")
                return
            
            details = detail_resp.json()
            games = details.get('games', [])
            
            # 2. Find the *specific* game object
            game_object = None
            for game in games:
                if game.get('position') == ap_position:
                    game_object = game
                    break # Found it

            if not game_object:
                logging.warning(f"[CHEESE_PUSH] No game_object for position {ap_position} in {tracker_id}.")
                return

            cheese_game_id = game_object.get('id')
            updated_at_timestamp = details.get('updated_at')
            current_owner_id = game_object.get('claimed_by_ct_user_id')

            if not cheese_game_id or not updated_at_timestamp:
                logging.error(f"[CHEESE_PUSH] Fetched details for {tracker_id} are invalid.")
                return

            # 3. Guardrail Check
            if is_tracked:
                if current_owner_id is not None and (my_ct_id is None or current_owner_id != my_ct_id):
                    logging.warning(f"[CHEESE_PUSH] Aborting claim for pos {ap_position}: Slot is claimed by user {current_owner_id}.")
                    return
            else: # is_tracked is False (un-claiming)
                if current_owner_id is not None and (my_ct_id is None or current_owner_id != my_ct_id):
                    logging.warning(f"[CHEESE_PUSH] Aborting un-claim for pos {ap_position}: We don't own it.")
                    return

            # 4. Prepare URL and Payload
            url = f"{CHEESE_BASE_URL}/tracker/{tracker_id}/game/{cheese_game_id}"
            payload = game_object.copy()
            
            if is_tracked:
                if my_ct_id is None:
                    # This is the "cold start" case. We're claiming a slot but don't know our ID.
                    # We send 'None' as our ID, but the API will assign it
                    # based on our auth token.
                    logging.debug(f"[CHEESE_PUSH] Claiming pos {ap_position} with unknown ct_user_id (first claim).")
                    payload['claimed_by_ct_user_id'] = None # Server will fill this
                else:
                    payload['claimed_by_ct_user_id'] = my_ct_id
                payload['availability_status'] = "claimed"
            else:
                payload['claimed_by_ct_user_id'] = None
                payload['availability_status'] = "unknown"
            
            # 5. Prepare final headers with the *CORRECT* precondition
            put_headers = base_headers.copy()
            owner_precondition = {
                "claimed_by_ct_user_id": game_object.get('claimed_by_ct_user_id'),
                "discord_username": game_object.get('discord_username')
            }
            put_headers['x-if-owner-is'] = json.dumps(owner_precondition)
            
            # 6. Send the update
            response = requests.put(url, json=payload, headers=put_headers, timeout=5)
            
            if response.status_code in [200, 204]:
                logging.debug(f"[CHEESE_PUSH] Success for pos {ap_position} (game {cheese_game_id})")
                
                # --- THIS IS THE "COLD START" FIX ---
                if is_tracked and my_ct_id is None:
                    response_data = response.json()
                    new_ct_id = response_data.get('claimed_by_ct_user_id')
                    if new_ct_id:
                        logging.info(f"[CHEESE_PUSH] LEARNED new ct_user_id: {new_ct_id}")
                        thread_user.cheese_user_id = new_ct_id
                        thread_session.commit()
                # --- END FIX ---
            else:
                logging.warning(f"[CHEESE_PUSH] Failed to set pos {ap_position} (game {cheese_game_id}): {response.status_code} {response.text}")

        except Exception as e:
             thread_session.rollback()
             logging.error(f"[CHEESE_PUSH] Error pushing pos {ap_position}: {e}", exc_info=True)
        finally:
            Session.remove()

    # 4. Process removals and additions in a background thread
    try:
        # Pass the user.id to be thread-safe
        user_id_for_thread = user.id
        threading.Thread(target=lambda: (
            [send_state(slot_id, False, user_id_for_thread) for slot_id in removed_slots],
            [send_state(slot_id, True, user_id_for_thread) for slot_id in added_slots]
        )).start()
    except Exception as e:
        logging.error(f"Failed to start push thread for user {user.id}: {e}")