import logging
import requests
import threading
import os
import json
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from datetime import datetime

from . import Session
from .models import User, TrackedRoom, UserRoomSubscription
from .api import token_required, log_api_call, handle_db_errors
from .encryption import encrypt_api_key, decrypt_api_key

load_dotenv()

bp = Blueprint('api_cheese', __name__)

CHEESE_BASE_URL = os.environ.get('CHEESE_BASE_URL', 'https://cheesetrackers.theincrediblewheelofchee.se/api')

def _extract_ap_room_id(url_string):
    """
    Helper to extract the room ID (UUID) from an Archipelago URL.
    Example: https://archipelago.gg/room/12345 -> 12345
    """
    if not url_string:
        return None
    try:
        parsed = urlparse(url_string)
        parts = parsed.path.strip('/').split('/')
        if len(parts) >= 2 and parts[0] == 'room':
            return parts[1]
    except Exception:
        pass
    return None

def setup_cheese_user_task(app, user_id):
    """
    The 'First-Time Setup' task.
    1. Fetches all trackers for this user from Cheese.
    2. Finds or Creates the corresponding TrackedRoom in our DB.
    3. Subscribes the user to that room.
    """
    with app.app_context():
        session = Session()
        try:
            user = session.query(User).get(user_id)
            if not user or not user.cheese_api_key:
                logging.warning(f"[CHEESE_SETUP] User {user_id} has no API key. Aborting.")
                return

            api_key = decrypt_api_key(user.cheese_api_key)
            if not api_key:
                logging.error(f"[CHEESE_SETUP] Failed to decrypt key for user {user_id}.")
                return

            logging.info(f"[CHEESE_SETUP] Starting discovery for user {user_id}...")

            # 1. Fetch User's Trackers from Cheese
            headers = {"Authorization": f"Bearer {api_key}"}
            try:
                resp = requests.get(f"{CHEESE_BASE_URL}/dashboard/tracker", headers=headers, timeout=15)
                resp.raise_for_status()
                trackers_list = resp.json()
            except Exception as e:
                logging.error(f"[CHEESE_SETUP] Network error fetching dashboard: {e}")
                return

            stats = {'linked': 0, 'created': 0}

            # 2. Iterate and Link
            for tracker_meta in trackers_list:
                ct_id = tracker_meta.get('tracker_id')
                room_link = tracker_meta.get('room_link')
                title = tracker_meta.get('title') or "Unknown Room"
                
                # We need at least an ID or a Link to proceed
                if not ct_id: 
                    continue

                # A. Try to find existing room by Cheese ID
                room = session.query(TrackedRoom).filter_by(cheese_tracker_id=ct_id).first()

                # B. Fallback: Try to find by AP Room ID (if we haven't linked it to Cheese yet)
                if not room and room_link:
                    ap_room_id = _extract_ap_room_id(room_link)
                    if ap_room_id:
                        room = session.query(TrackedRoom).filter_by(room_id=ap_room_id).first()
                        # If we found it via AP ID, link the Cheese ID now
                        if room and not room.cheese_tracker_id:
                            room.cheese_tracker_id = ct_id
                            logging.info(f"[CHEESE_SETUP] Linked existing AP room {ap_room_id} to Cheese ID {ct_id}")

                # C. If still no room, create it
                if not room:
                    # We fetch the full details to populate the cache immediately
                    # This ensures the user sees data instantly without waiting for the next poll
                    try:
                        detail_resp = requests.get(f"{CHEESE_BASE_URL}/tracker/{ct_id}", headers=headers, timeout=10)
                        if detail_resp.ok:
                            full_data = detail_resp.json()
                            ap_room_id_extracted = _extract_ap_room_id(room_link) or "PENDING_DISCOVERY_" + ct_id[:8]
                            hostname = "archipelago.gg" # Default, or extract from room_link
                            try:
                                if room_link:
                                    hostname = urlparse(room_link).hostname or "archipelago.gg"
                            except: pass

                            # Parse timestamp
                            updated_at_dt = None
                            if full_data.get('updated_at'):
                                try:
                                    updated_at_dt = datetime.fromisoformat(full_data.get('updated_at').replace('Z', '+00:00'))
                                except ValueError:
                                    pass

                            room = TrackedRoom(
                                room_id=ap_room_id_extracted,
                                hostname=hostname,
                                cheese_tracker_id=ct_id,
                                cached_cheese_json=json.dumps(full_data),
                                cheese_updated_at=updated_at_dt,
                                cached_full_address=hostname # Placeholder until AP poll runs
                            )
                            session.add(room)
                            session.flush() # Generate ID
                            stats['created'] += 1
                            logging.info(f"[CHEESE_SETUP] Created new global room for Cheese ID {ct_id}")
                    except Exception as e:
                        logging.error(f"[CHEESE_SETUP] Failed to fetch/create details for {ct_id}: {e}")
                        continue

                # 3. Subscribe User (if room exists/was created)
                if room:
                    # Ensure subscription
                    sub = session.query(UserRoomSubscription).filter_by(user_id=user.id, room_id=room.id).first()
                    if not sub:
                        session.add(UserRoomSubscription(
                            user_id=user.id, 
                            room_id=room.id, 
                            alias=title, 
                            icon_name='cheese'
                        ))
                        stats['linked'] += 1
            
            # Update user state
            user.cheese_last_sync = datetime.utcnow()
            session.commit()
            logging.info(f"[CHEESE_SETUP] User {user_id} setup complete. {stats}")

        except Exception as e:
            session.rollback()
            logging.error(f"[CHEESE_SETUP] Critical failure for user {user_id}: {e}", exc_info=True)
        finally:
            Session.remove()


@bp.route('/auth', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def connect_cheese_account(current_user):
    """
    Sets the Cheese API key and kicks off the discovery task.
    """
    if current_user.is_guest:
        return jsonify({'error': 'Guests cannot use integrations. Please log in.'}), 403
    
    data = request.json
    api_key = data.get('api_key')

    if not api_key or not isinstance(api_key, str) or len(api_key.strip()) == 0 or len(api_key) > 256:
        return jsonify({'error': 'Invalid or missing api_key.'}), 400

    api_key = api_key.strip()

    # 1. Validate Key (Pre-flight)
    try:
        test_headers = {"Authorization": f"Bearer {api_key}"}
        test_resp = requests.get(f"{CHEESE_BASE_URL}/dashboard/tracker", headers=test_headers, timeout=10)
        
        if test_resp.status_code == 401:
            logging.warning(f"[CHEESE_AUTH] User {current_user.id} provided invalid API key.")
            return jsonify({'error': 'Invalid API Key. Please check the key and try again.'}), 400
        
        test_resp.raise_for_status() 

    except requests.exceptions.RequestException as e:
        logging.error(f"[CHEESE_AUTH] Network error testing key: {e}")
        return jsonify({'error': 'Could not verify key with Cheese Tracker. The server may be down.'}), 502

    # 2. Save Encrypted Key
    session = Session()
    user = session.merge(current_user)
    
    encrypted_key = encrypt_api_key(api_key)
    if not encrypted_key:
        return jsonify({'error': 'Failed to secure API key.'}), 500

    user.cheese_api_key = encrypted_key
    session.commit()

    # 3. Kick off Background Discovery
    try:
        app_context = current_app._get_current_object()
        threading.Thread(
            target=setup_cheese_user_task, 
            args=(app_context, user.id,)
        ).start()
    except Exception as e:
        logging.error(f"Failed to start setup thread for user {user.id}: {e}")
        
    return jsonify({
        'message': 'Connected! We are finding your rooms now...', 
        'is_connected': True
    })

@bp.route('/sync', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def trigger_manual_sync(current_user):
    """
    Manually triggers discovery/linking.
    Useful if the user created a new tracker on the website and wants it to appear in the app immediately.
    """
    if current_user.is_guest:
        return jsonify({'error': 'Guests cannot use integrations.'}), 403
    if not current_user.cheese_api_key:
        return jsonify({'error': 'Not connected to Cheese Tracker.'}), 400

    app_context = current_app._get_current_object()

    # Re-use the setup task for manual sync
    threading.Thread(
        target=setup_cheese_user_task, 
        args=(app_context, current_user.id,)
    ).start()
        
    return jsonify({'message': 'Sync started. Your new rooms should appear shortly.'})


def push_new_room_to_cheese(app, user_id, tracker_url, ap_room_id, room_url, alias):
    """
    (V4 Refactored) Pushes a new room to Cheese Tracker.
    Fixes self-deadlock by not holding a DB session during network calls.
    """
    api_key = None
    
    # === 1. PRE-FLIGHT: Get API key ===
    # Use a *temporary* session just to get the key
    with app.app_context():
        temp_session = Session()
        try:
            user = temp_session.query(User).filter_by(id=user_id).first()
            if not user or not user.cheese_api_key:
                logging.warning(f"[CHEESE_PUSH_NEW] Aborting push for {tracker_url}: No API key.")
                return

            api_key = decrypt_api_key(user.cheese_api_key)
            if not api_key:
                logging.error(f"[CHEESE_PUSH_NEW] Failed to decrypt API key for user {user_id}. Aborting push.")
                return
        except Exception as e:
            logging.error(f"[CHEESE_PUSH_NEW] Error in pre-flight: {e}", exc_info=True)
            return
        finally:
            Session.remove() # Close the temp session

    # === 2. NETWORK PHASE: No DB session open! ===
    cheese_tracker_id = None
    try:
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
        
        tracker_data = {}
        if response_get.ok:
            tracker_data = response_get.json()
        
        # Step 3: Create the PUT payload
        current_title = tracker_data.get('title', '')
        final_title = current_title if current_title else alias
            
        put_payload = {
            "title": final_title,
            "description": tracker_data.get('description', ''),
            "owner_ct_user_id": tracker_data.get('owner_ct_user_id'),
            "lock_settings": tracker_data.get('lock_settings', False),
            "global_ping_policy": tracker_data.get('global_ping_policy'),
            "room_link": room_url,
            "inactivity_threshold_yellow_hours": tracker_data.get('inactivity_threshold_yellow_hours', 24),
            "inactivity_threshold_red_hours": tracker_data.get('inactivity_threshold_red_hours', 48),
            "require_authentication_to_claim": tracker_data.get('require_authentication_to_claim', False)
        }
        
        put_headers = headers.copy()
        if 'updated_at' in tracker_data:
            put_headers['If-Unmodified-Since'] = tracker_data.get('updated_at')
        
        # Step 5: PUT the update
        response_put = requests.put(f"{CHEESE_BASE_URL}/tracker/{cheese_tracker_id}", json=put_payload, headers=put_headers, timeout=10)
        
        if not (response_put.status_code == 200 or response_put.status_code == 204):
            logging.warning(f"[CHEESE_PUSH_NEW] Failed (PUT) to update title/room_link for {cheese_tracker_id}: {response_put.status_code} {response_put.text}")

    except requests.exceptions.ReadTimeout:
        logging.error(f"[CHEESE_PUSH_NEW] Network timeout connecting to {CHEESE_BASE_URL}. Is local server running and responsive?", exc_info=True)
        return
    except Exception as e:
        logging.error(f"[CHEESE_PUSH_NEW] Error during network phase: {e}", exc_info=True)
        return

    # === 3. DATABASE PHASE: Now we link the ID ===
    if not cheese_tracker_id:
        return # Should have already returned, but as a safeguard

    with app.app_context():
        session = Session()
        try:
            local_room = session.query(TrackedRoom).filter_by(room_id=ap_room_id).first()
            if local_room:
                local_room.cheese_tracker_id = cheese_tracker_id
                session.commit()
                logging.info(f"[CHEESE_PUSH_NEW] Successfully created/linked {ap_room_id} to Cheese ID {cheese_tracker_id}.")
            else:
                logging.error(f"[CHEESE_PUSH_NEW] Race condition: Could not find local room {ap_room_id} to link.")
        except Exception as e:
            session.rollback()
            logging.error(f"[CHEESE_PUSH_NEW] Error in database phase: {e}", exc_info=True)
        finally:
            Session.remove()

def push_slot_changes_to_cheese(app, user_id, room_db_id, added_slots, removed_slots):
    """
    (Refactored V13) Pushes changes to Cheese Tracker.
    Fixes self-deadlock by not holding a DB session during network calls.
    """
    api_key = None
    tracker_id = None
    my_ct_id = None
    
    # === 1. PRE-FLIGHT: Get API key & Tracker ID ===
    # Use a *temporary* session just to get info
    with app.app_context():
        temp_session = Session()
        try:
            user = temp_session.query(User).filter_by(id=user_id).first()
            if not user or not user.cheese_api_key:
                logging.warning("[CHEESE_PUSH] Aborting: No user or API key.")
                return

            api_key = decrypt_api_key(user.cheese_api_key)
            if not api_key:
                logging.warning("[CHEESE_PUSH] Aborting: Could not decrypt API key.")
                return
            
            my_ct_id = user.cheese_user_id # Get the user's cheese ID

            local_room = temp_session.query(TrackedRoom.cheese_tracker_id).filter_by(id=room_db_id).first()
            if not local_room or not local_room.cheese_tracker_id:
                logging.warning(f"[CHEESE_PUSH] Aborting: No cheese_tracker_id for room {room_db_id}.")
                return
                
            tracker_id = local_room.cheese_tracker_id
        except Exception as e:
            logging.error(f"[CHEESE_PUSH] Error in pre-flight: {e}", exc_info=True)
            return # Don't proceed if we failed
        finally:
            Session.remove() # Close the temp session

    # === 2. NETWORK PHASE: No DB session open! ===
    
    base_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Helper function to send the state
    def send_state(app, ap_position, is_tracked, current_user_id_for_thread, initial_ct_id):
        # The thread will create its *own* session
        # This function is already safe (Network -> DB)
        with app.app_context():
            thread_session = Session()
            try:
                # We pass the initial_ct_id so we don't need to re-fetch the user
                # *unless* we are learning the ID.
                my_ct_id = initial_ct_id

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
                    payload['claimed_by_ct_user_id'] = my_ct_id
                    payload['availability_status'] = "claimed"
                else:
                    payload['claimed_by_ct_user_id'] = None
                    payload['availability_status'] = "unknown"
                
                # 5. Prepare final headers
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
                    
                    if is_tracked and my_ct_id is None:
                        response_data = response.json()
                        new_ct_id = response_data.get('claimed_by_ct_user_id')
                        if new_ct_id:
                            logging.info(f"[CHEESE_PUSH] LEARNED new ct_user_id: {new_ct_id}")
                            # Now we need to fetch the user to save it
                            thread_user = thread_session.query(User).filter_by(id=current_user_id_for_thread).first()
                            if thread_user:
                                thread_user.cheese_user_id = new_ct_id
                                thread_session.commit()
                else:
                    logging.warning(f"[CHEESE_PUSH] Failed to set pos {ap_position} (game {cheese_game_id}): {response.status_code} {response.text}")

            except Exception as e:
                 if thread_session: thread_session.rollback()
                 logging.error(f"[CHEESE_PUSH] Error pushing pos {ap_position}: {e}", exc_info=True)
            finally:
                if thread_session: Session.remove()

    # 4. Process removals and additions in a background thread
    try: 
        threading.Thread(target=lambda: (
            [send_state(app, slot_id, False, user_id, my_ct_id) for slot_id in removed_slots],
            [send_state(app, slot_id, True, user_id, my_ct_id) for slot_id in added_slots]
        )).start()
    except Exception as e:
        logging.error(f"Failed to start push thread for user {user_id}: {e}")