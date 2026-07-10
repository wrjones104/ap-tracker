import logging
import requests
import threading
import os
import json
import time
import re
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from datetime import datetime, timedelta

from . import Session
from .models import User, TrackedRoom, UserRoomSubscription, UserTrackedSlot
from .api import token_required, log_api_call, handle_db_errors
from .encryption import encrypt_api_key, decrypt_api_key
from .utils import get_cheese_headers, extract_ap_room_id

load_dotenv()

bp = Blueprint('api_cheese', __name__)

CHEESE_BASE_URL = os.environ.get('CHEESE_BASE_URL', 'https://cheesetrackers.theincrediblewheelofchee.se/api')
CHEESE_DELAY = 60.0
    
def setup_cheese_user_task(app, user_id):
    """
    The 'First-Time Setup' & 'Manual Sync' task.
    """
    with app.app_context():
        session = Session()
        try:
            user = session.query(User).get(user_id)
            if not user or not user.cheese_api_key:
                logging.warning(f"[CHEESE_SETUP] User {user_id} has no API key. Aborting.")
                return

            user.is_syncing_cheese = True
            user.cheese_sync_started_at = datetime.utcnow()
            session.commit()
            
            # --- KEY DECRYPTION ---
            api_key = decrypt_api_key(user.cheese_api_key)
            if not api_key:
                logging.error(f"[CHEESE_DEBUG] Failed to decrypt key for user {user_id}.")
                user.is_syncing_cheese = False
                session.commit()
                return

            my_cheese_id = user.cheese_user_id
            discord_username = user.discord_username.strip().lower() if user.discord_username else None

            # Close/release DB session before starting network calls to prevent holding connection/locks
            Session.remove()

            resolved_cheese_user_id = my_cheese_id
            trackers_list = []

            # --- REQUESTS SESSION FOR NETWORK OPERATIONS ---
            with requests.Session() as req_session:
                req_session.headers.update(get_cheese_headers())
                req_session.headers['Authorization'] = f"Bearer {api_key}"
                
                # 1. Verify Self
                try:
                    me_resp = req_session.get(f"{CHEESE_BASE_URL}/user/self", timeout=10)
                    if me_resp.ok:
                        me_data = me_resp.json()
                        if me_data.get('id'):
                            resolved_cheese_user_id = me_data['id']
                            logging.info(f"[CHEESE_DEBUG] Resolved Cheese User ID: {resolved_cheese_user_id}")
                except Exception as e:
                    logging.warning(f"[CHEESE_DEBUG] Failed to fetch /user/self: {e}")
                
                # 2. Fetch User's Trackers List
                try:
                    logging.info(f"[CHEESE_DEBUG] Fetching dashboard for user {user_id}...")
                    resp = req_session.get(f"{CHEESE_BASE_URL}/dashboard/tracker", timeout=15)
                    resp.raise_for_status()
                    trackers_list = resp.json()
                    logging.info(f"[CHEESE_DEBUG] Dashboard returned {len(trackers_list)} trackers.")
                except Exception as e:
                    logging.error(f"[CHEESE_DEBUG] Network error fetching dashboard: {e}")
                    # Re-open session briefly to release syncing lock on failure
                    session = Session()
                    user = session.query(User).get(user_id)
                    if user:
                        user.is_syncing_cheese = False
                        session.commit()
                    return

                # --- FETCH DETAILS FOR EACH TRACKER ---
                # Do all slow network queries and sleeps in memory first!
                detailed_trackers = []
                for tracker_meta in trackers_list:
                    if tracker_meta.get('dashboard_override_visibility') is False:
                        continue
                    ct_id = tracker_meta.get('tracker_id')
                    room_link = tracker_meta.get('room_link')
                    title = tracker_meta.get('title') or "Unknown Room"
                    
                    if not ct_id: continue
                    
                    time.sleep(0.5)
                    try:
                        detail_resp = req_session.get(f"{CHEESE_BASE_URL}/tracker/{ct_id}", timeout=10)
                        if detail_resp.ok:
                            full_data = detail_resp.json()
                            detailed_trackers.append({
                                'ct_id': ct_id,
                                'room_link': room_link,
                                'title': title,
                                'full_data': full_data
                            })
                    except Exception as e:
                        logging.error(f"[CHEESE_DEBUG] Failed to fetch details for {ct_id}: {e}")
                        continue

            # === DATABASE TRANSACTION START ===
            # Run all DB operations in a single fast transaction
            session = Session()
            user = session.query(User).get(user_id)
            if not user:
                return

            if resolved_cheese_user_id != user.cheese_user_id:
                user.cheese_user_id = resolved_cheese_user_id
                session.commit()
                user = session.query(User).get(user_id)

            my_cheese_id = user.cheese_user_id

            stats = {'linked': 0, 'created': 0, 'slots_synced': 0, 'pruned': 0}
            found_cheese_tracker_ids = set()
            processed_room_ids = set()

            for tracker_item in detailed_trackers:
                ct_id = tracker_item['ct_id']
                room_link = tracker_item['room_link']
                title = tracker_item['title']
                full_data = tracker_item['full_data']
                
                found_cheese_tracker_ids.add(ct_id)

                room = session.query(TrackedRoom).filter_by(cheese_tracker_id=ct_id).first()

                if not room and room_link:
                    ap_room_id = extract_ap_room_id(room_link)
                    if ap_room_id:
                        room = session.query(TrackedRoom).filter_by(room_id=ap_room_id).first()
                        if room and not room.cheese_tracker_id:
                            room.cheese_tracker_id = ct_id
                            logging.info(f"[CHEESE_DEBUG] Linked existing AP room {ap_room_id} to Cheese ID {ct_id}")

                if not room:
                    ap_room_id_extracted = extract_ap_room_id(room_link) or "PENDING_DISCOVERY_" + ct_id[:8]
                    hostname = "archipelago.gg"
                    try:
                        if room_link:
                            hostname = urlparse(room_link).hostname or "archipelago.gg"
                    except: pass

                    updated_at_dt = None
                    if full_data.get('updated_at'):
                        try:
                            updated_at_dt = datetime.fromisoformat(full_data.get('updated_at').replace('Z', '+00:00'))
                        except ValueError: pass

                    logging.info(f"[CHEESE_DEBUG] Creating new room: {ap_room_id_extracted}")
                    room = TrackedRoom(
                        room_id=ap_room_id_extracted,
                        hostname=hostname,
                        cheese_tracker_id=ct_id,
                        cached_cheese_json=json.dumps(full_data),
                        cheese_updated_at=updated_at_dt,
                        cached_full_address=hostname
                    )
                    session.add(room)
                    session.flush()
                    stats['created'] += 1
                else:
                    room.cached_cheese_json = json.dumps(full_data)
                    if full_data.get('updated_at'):
                        try:
                            room.cheese_updated_at = datetime.fromisoformat(full_data.get('updated_at').replace('Z', '+00:00'))
                        except ValueError: pass

                if room:
                    processed_room_ids.add(room.id)

                # Subscribe User & Sync Slots
                sub = session.query(UserRoomSubscription).filter_by(user_id=user.id, room_id=room.id).first()
                if not sub:
                    session.add(UserRoomSubscription(
                        user_id=user.id, room_id=room.id, alias=title, icon_name='cheese'
                    ))
                    stats['linked'] += 1
                    session.flush() 

                games = full_data.get('games', [])
                slots_found = set()

                for game in games:
                    if my_cheese_id and game.get('claimed_by_ct_user_id') == my_cheese_id:
                        slots_found.add(game.get('position'))
                    elif discord_username:
                        eff_discord = game.get('effective_discord_username')
                        if eff_discord and eff_discord.strip().lower() == discord_username:
                            slots_found.add(game.get('position'))
                            found_ct_id = game.get('claimed_by_ct_user_id')
                            if found_ct_id and not my_cheese_id:
                                user.cheese_user_id = found_ct_id
                                my_cheese_id = found_ct_id

                if slots_found:
                    existing_slots = session.query(UserTrackedSlot.slot_id).filter_by(
                        user_id=user.id, room_id=room.id
                    ).all()
                    existing_set = {s[0] for s in existing_slots}

                    for slot_id in slots_found:
                        if slot_id not in existing_set:
                            session.add(UserTrackedSlot(
                                user_id=user.id,
                                room_id=room.id,
                                slot_id=slot_id,
                                notify_finished=user.notify_finished_default
                            ))
                            stats['slots_synced'] += 1

            # 3. Prune stale subscriptions
            # A subscription is stale if it is linked to a Cheese tracker that is no longer present on the user's dashboard.
            # We use the list of all trackers returned by the dashboard API (all_dashboard_tracker_ids) rather than found_cheese_tracker_ids
            # to avoid pruning rooms that are still on the user's dashboard but failed to fetch due to a timeout or other error.
            all_dashboard_tracker_ids = {
                t.get('tracker_id') for t in trackers_list 
                if t.get('tracker_id') and t.get('dashboard_override_visibility') is not False
            }

            stale_subs_query = session.query(UserRoomSubscription)\
                .join(TrackedRoom)\
                .filter(UserRoomSubscription.user_id == user.id)\
                .filter(UserRoomSubscription.is_archived == False) \
                .filter(TrackedRoom.cheese_tracker_id.isnot(None))

            if processed_room_ids:
                stale_subs_query = stale_subs_query.filter(UserRoomSubscription.room_id.notin_(processed_room_ids))

            if all_dashboard_tracker_ids:
                stale_subs_query = stale_subs_query.filter(TrackedRoom.cheese_tracker_id.notin_(all_dashboard_tracker_ids))

            stale_subs = stale_subs_query.all()

            for sub in stale_subs:
                logging.info(f"[CHEESE_DEBUG] Pruning stale subscription for user {user.id}: Room {sub.room_id}")
                session.delete(sub)
                stats['pruned'] += 1
            
            session.commit()
            logging.info(f"[CHEESE_DEBUG] Initial sync loop complete. Stats: {stats}")

            # --- REQUESTS SESSION END ---

            try:
                # HEALING PHASE: Pushing orphaned rooms back to Cheese
                from sqlalchemy.orm import selectinload
                orphaned_subs = session.query(UserRoomSubscription)\
                    .options(selectinload(UserRoomSubscription.room))\
                    .join(TrackedRoom)\
                    .filter(UserRoomSubscription.user_id == user.id)\
                    .filter(TrackedRoom.cheese_tracker_id.is_(None))\
                    .filter(~TrackedRoom.room_id.startswith("PENDING_DISCOVERY"))\
                    .all()

                rooms_to_push = []
                for sub in orphaned_subs:
                    room = sub.room
                    if room and room.tracker_id and room.hostname: 
                        rooms_to_push.append({
                            'room_id': room.room_id,
                            'tracker_url': f"https://{room.hostname}/tracker/{room.tracker_id}",
                            'room_url': f"https://{room.hostname}/room/{room.room_id}",
                            'alias': sub.alias
                        })
                
                if rooms_to_push:
                    logging.info(f"[CHEESE_DEBUG] Found {len(rooms_to_push)} orphaned rooms to heal. Closing DB session for network operations.")
                    
                    # Close the session before starting the synchronous push loop
                    # This ensures push_new_room_to_cheese (which opens its own session)
                    # doesn't conflict with the current one.
                    Session.remove()

                    # Execute network calls safely
                    for data in rooms_to_push:
                        logging.info(f"[CHEESE_DEBUG] Healing orphaned room: {data['room_id']}")
                        push_new_room_to_cheese(
                            app, 
                            user_id, 
                            data['tracker_url'], 
                            data['room_id'], 
                            data['room_url'], 
                            data['alias']
                        )
                else:
                    logging.info("[CHEESE_DEBUG] No orphaned rooms found.")

            except Exception as e:
                logging.error(f"[CHEESE_DEBUG] Error during healing phase: {e}", exc_info=True)
            
            # --- RE-FETCH USER TO UNLOCK ---
            logging.info(f"[CHEESE_DEBUG] Sync task finished. Unlocking user {user_id}...")
            session = Session()
            fresh_user = session.query(User).get(user_id)
            if fresh_user:
                fresh_user.is_syncing_cheese = False
                fresh_user.cheese_last_sync = datetime.utcnow()
                session.commit()
            logging.info(f"[CHEESE_DEBUG] User {user_id} unlocked.")

        except Exception as e:
            session.rollback()
            try:
                user = session.query(User).get(user_id)
                if user:
                    user.is_syncing_cheese = False
                    session.commit()
            except: pass
            logging.error(f"[CHEESE_DEBUG] Critical failure for user {user_id}: {e}", exc_info=True)
        finally:
            Session.remove()

@bp.route('/auth', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def connect_cheese_account(current_user):
    """
    Sets the Cheese API key and kicks off the discovery task.
    Allowed for Guests because the API Key provides the identity.
    """
    data = request.json
    api_key = data.get('api_key')

    if not api_key or not isinstance(api_key, str) or len(api_key.strip()) == 0:
        return jsonify({'error': 'Invalid or missing api_key.'}), 400

    api_key = api_key.strip()

    # 1. Validate Key & Fetch Identity
    try:
        test_headers = get_cheese_headers() 
        test_headers["Authorization"] = f"Bearer {api_key}"

        test_resp = requests.get(f"{CHEESE_BASE_URL}/user/self", headers=test_headers, timeout=10)
        
        if test_resp.status_code == 401:
            return jsonify({'error': 'Invalid API Key.'}), 400
        
        test_resp.raise_for_status()
        
        me_data = test_resp.json()
        cheese_id = me_data.get('id')
        cheese_discord_name = me_data.get('discord_username')

        if not cheese_id:
            logging.error(f"[CHEESE_AUTH] /user/self did not return an ID. Response: {me_data}")
            return jsonify({'error': 'Could not verify Cheese identity.'}), 502

    except requests.exceptions.RequestException as e:
        logging.error(f"[CHEESE_AUTH] Network error testing key: {e}")
        return jsonify({'error': 'Could not verify key with Cheese Tracker.'}), 502

    # 2. Save Data & SET SYNC FLAG SYNCHRONOUSLY
    session = Session()
    user = session.merge(current_user)
    
    encrypted_key = encrypt_api_key(api_key)
    user.cheese_api_key = encrypted_key
    user.cheese_user_id = cheese_id
    
    # Set flags so subsequent polls see "Syncing" immediately
    user.is_syncing_cheese = True
    user.cheese_sync_started_at = datetime.utcnow()
    
    if user.is_guest and cheese_discord_name:
        user.discord_username = cheese_discord_name
        logging.info(f"[CHEESE_AUTH] Guest user {user.id} identified as '{cheese_discord_name}' via Cheese.")

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
        'message': f"Connected as {cheese_discord_name or 'Cheese User'}! Syncing now...", 
        'is_connected': True
    })

@bp.route('/auth', methods=['DELETE'])
@handle_db_errors
@log_api_call
@token_required
def disconnect_cheese_account(current_user):
    """
    Removes the Cheese API key and ID.
    """
    session = Session()
    user = session.merge(current_user)
    user.cheese_api_key = None
    user.cheese_user_id = None 
    user.is_syncing_cheese = False # Reset flag just in case
    session.commit()
    
    return jsonify({'message': 'Disconnected from Cheese Tracker.'})

@bp.route('/sync', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def trigger_manual_sync(current_user):
    """
    Manually triggers discovery/linking.
    Sets flag SYNCHRONOUSLY to prevent race conditions.
    """
    if not current_user.cheese_api_key:
        return jsonify({'error': 'Not connected to Cheese Tracker.'}), 400

    session = Session()
    user = session.merge(current_user)
    
    if user.is_syncing_cheese:
        if user.cheese_sync_started_at and (datetime.utcnow() - user.cheese_sync_started_at) < timedelta(minutes=15):
            return jsonify({'error': 'Sync already in progress.'}), 429
    
    # LOCK IMMEDIATELY
    user.is_syncing_cheese = True
    user.cheese_sync_started_at = datetime.utcnow()
    session.commit()

    app_context = current_app._get_current_object()
    threading.Thread(
        target=setup_cheese_user_task, 
        args=(app_context, user.id,)
    ).start()
        
    return jsonify({'message': 'Sync started.'})


def push_new_room_to_cheese(app, user_id, tracker_url, ap_room_id, room_url, alias):
    """
    (V4 Refactored) Pushes a new room to Cheese Tracker.
    """
    logging.info(f"[CHEESE_DEBUG] push_new_room_to_cheese called for {ap_room_id}")
    api_key = None
    
    # === 1. PRE-FLIGHT ===
    with app.app_context():
        temp_session = Session()
        try:
            user = temp_session.query(User).filter_by(id=user_id).first()
            if not user or not user.cheese_api_key:
                logging.warning(f"[CHEESE_DEBUG] Aborting push for {tracker_url}: No API key.")
                return

            api_key = decrypt_api_key(user.cheese_api_key)
            if not api_key:
                logging.error(f"[CHEESE_DEBUG] Failed to decrypt API key for user {user_id}. Aborting push.")
                return
        except Exception as e:
            logging.error(f"[CHEESE_DEBUG] Error in pre-flight: {e}", exc_info=True)
            return
        finally:
            Session.remove() 

    # === 2. NETWORK PHASE ===
    cheese_tracker_id = None
    try:
        headers = get_cheese_headers()
        headers["Authorization"] = f"Bearer {api_key}"
        
        # Step 1: POST to create/get the tracker
        payload = {"url": tracker_url}
        response_post = requests.post(f"{CHEESE_BASE_URL}/tracker", json=payload, headers=headers, timeout=10)

        if not (response_post.status_code == 200 or response_post.status_code == 201):
            logging.warning(f"[CHEESE_DEBUG] Failed (POST) to create tracker for {tracker_url}: {response_post.status_code} {response_post.text}")
            return
            
        data = response_post.json()
        cheese_tracker_id = data.get('tracker_id')
        
        if not cheese_tracker_id:
            logging.error(f"[CHEESE_DEBUG] Succeeded POST, but no tracker_id in response for {tracker_url}.")
            return

        time.sleep(CHEESE_DELAY)

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
        
        time.sleep(CHEESE_DELAY)

        # Step 5: PUT the update
        response_put = requests.put(f"{CHEESE_BASE_URL}/tracker/{cheese_tracker_id}", json=put_payload, headers=put_headers, timeout=10)
        
        if not (response_put.status_code == 200 or response_put.status_code == 204):
            logging.warning(f"[CHEESE_DEBUG] Failed (PUT) to update title/room_link for {cheese_tracker_id}: {response_put.status_code} {response_put.text}")

    except requests.exceptions.ReadTimeout:
        logging.error(f"[CHEESE_DEBUG] Network timeout connecting to {CHEESE_BASE_URL}.", exc_info=True)
        return
    except Exception as e:
        logging.error(f"[CHEESE_DEBUG] Error during network phase: {e}", exc_info=True)
        return

    # === 3. DATABASE PHASE ===
    if not cheese_tracker_id:
        return 

    room_db_id_for_slots = None
    slot_ids_to_claim = []

    with app.app_context():
        session = Session()
        try:
            local_room = session.query(TrackedRoom).filter_by(room_id=ap_room_id).first()
            if local_room:
                try:
                    local_room.cheese_tracker_id = cheese_tracker_id
                    session.commit()
                    logging.info(f"[CHEESE_DEBUG] Successfully created/linked {ap_room_id} to Cheese ID {cheese_tracker_id}.")
                    room_db_id_for_slots = local_room.id
                
                except IntegrityError:
                    session.rollback()
                    logging.warning(f"[CHEESE_DEBUG] Collision: Cheese ID {cheese_tracker_id} is already assigned to another room.")
                    return                 
                
                # Fetch the slots we need to push while the session is alive
                try:
                    slots_to_claim = session.query(UserTrackedSlot.slot_id).filter_by(
                        user_id=user_id, 
                        room_id=local_room.id
                    ).all()
                    
                    if slots_to_claim:
                        slot_ids_to_claim = [s[0] for s in slots_to_claim]
                except Exception as e:
                     logging.error(f"[CHEESE_DEBUG] Error querying catch-up claim: {e}")
            else:
                logging.error(f"[CHEESE_DEBUG] Race condition: Could not find local room {ap_room_id} to link.")
        except Exception as e:
            session.rollback()
            logging.error(f"[CHEESE_DEBUG] Error in database phase: {e}", exc_info=True)
        finally:
            Session.remove()

    # === 4. TRIGGER SLOT CATCH-UP ===
    if room_db_id_for_slots and slot_ids_to_claim:
        logging.info(f"[CHEESE_DEBUG] Found {len(slot_ids_to_claim)} slots waiting to be claimed. Triggering synchronous push.")
        try:
            push_slot_changes_to_cheese(app, user_id, room_db_id_for_slots, slot_ids_to_claim, [])
        except Exception as e:
            logging.error(f"[CHEESE_DEBUG] Error triggering slot push: {e}")

def _background_push_worker(app, user_id, tracker_id, added_slots, removed_slots, my_ct_id, base_headers):
    """
    Dedicated worker function to handle multiple slot pushes with a single DB session.
    """
    logging.info(f"[CHEESE_DEBUG_WORKER] Starting synchronous slot push for user {user_id} on tracker {tracker_id}")
    notifications_outbox = []
    with app.app_context():
        session = Session()
        try:
            # Process removals
            for slot_id in removed_slots:
                send_state(session, app, slot_id, False, user_id, my_ct_id, tracker_id, base_headers, notifications_outbox)
            
            # Process additions
            for slot_id in added_slots:
                send_state(session, app, slot_id, True, user_id, my_ct_id, tracker_id, base_headers, notifications_outbox)

            session.commit()
            logging.info(f"[CHEESE_DEBUG_WORKER] Finished slot push.")
            
            # Send notifications AFTER successful commit
            if notifications_outbox:
                try:
                    from firebase_admin import messaging
                    for tokens, messages in notifications_outbox:
                        messaging.send_each(messages)
                        logging.info(f"[CHEESE_DEBUG] Sent collision push notification after commit to user {user_id}")
                except Exception as p_err:
                    logging.error(f"[CHEESE_DEBUG] Failed to send collision push after commit: {p_err}")
        except Exception as e:
            session.rollback()
            logging.error(f"[CHEESE_DEBUG_WORKER] Worker failed for user {user_id}: {e}")
        finally:
            Session.remove()

def push_slot_changes_to_cheese(app, user_id, room_db_id, added_slots, removed_slots):
    """
    Pushes changes to Cheese Tracker.
    NOW RUNS SYNCHRONOUSLY.
    """
    api_key = None
    tracker_id = None
    my_ct_id = None
    
    # === 1. PRE-FLIGHT ===
    with app.app_context():
        temp_session = Session()
        try:
            user = temp_session.query(User).filter_by(id=user_id).first()
            if not user or not user.cheese_api_key:
                logging.warning("[CHEESE_DEBUG] Aborting: No user or API key.")
                return

            api_key = decrypt_api_key(user.cheese_api_key)
            if not api_key:
                logging.warning("[CHEESE_DEBUG] Aborting: Could not decrypt API key.")
                return
            
            my_ct_id = user.cheese_user_id

            local_room = temp_session.query(TrackedRoom.cheese_tracker_id).filter_by(id=room_db_id).first()
            if not local_room or not local_room.cheese_tracker_id:
                logging.warning(f"[CHEESE_DEBUG] Aborting: No cheese_tracker_id for room {room_db_id}.")
                return
                
            tracker_id = local_room.cheese_tracker_id
        except Exception as e:
            logging.error(f"[CHEESE_DEBUG] Error in pre-flight: {e}", exc_info=True)
            return
        finally:
            Session.remove()

    # === 2. BACKGROUND WORKER (Synchronous) ===
    
    base_headers = get_cheese_headers()
    base_headers["Authorization"] = f"Bearer {api_key}"

    try: 
        # Called directly to block execution until finished
        _background_push_worker(app, user_id, tracker_id, added_slots, removed_slots, my_ct_id, base_headers)
    except Exception as e:
        logging.error(f"Failed to run push worker for user {user_id}: {e}")

def send_state(session, app, ap_position, is_tracked, current_user_id_for_thread, initial_ct_id, tracker_id, base_headers, notifications_outbox=None):
    """
    Helper function to send the state to Cheese Tracker.
    """
    try:
        my_ct_id = initial_ct_id

        # 1. FETCH LATEST STATE
        detail_resp = requests.get(f"{CHEESE_BASE_URL}/tracker/{tracker_id}", headers=base_headers, timeout=10)
        if not detail_resp.ok:
            logging.warning(f"[CHEESE_DEBUG] Failed to fetch details for {tracker_id} before push.")
            return
        
        details = detail_resp.json()
        games = details.get('games', [])
        
        # 2. Find the *specific* game object
        game_object = None
        for game in games:
            if game.get('position') == ap_position:
                game_object = game
                break 

        if not game_object:
            logging.warning(f"[CHEESE_DEBUG] No game_object for position {ap_position} in {tracker_id}.")
            return

        cheese_game_id = game_object.get('id')
        updated_at_timestamp = details.get('updated_at')
        current_owner_id = game_object.get('claimed_by_ct_user_id')
        ct_discord = game_object.get('discord_username')
        ct_eff_discord = game_object.get('effective_discord_username')

        if not cheese_game_id or not updated_at_timestamp:
            logging.error(f"[CHEESE_DEBUG] Fetched details for {tracker_id} are invalid.")
            return

        # 3. Guardrail Check
        user = session.query(User).filter_by(id=current_user_id_for_thread).first()
        my_discord = user.discord_username.strip() if (user and user.discord_username) else None
        my_discord_clean = my_discord.lower() if my_discord else None

        ct_discord_clean = ct_discord.strip().lower() if ct_discord else None
        ct_eff_discord_clean = ct_eff_discord.strip().lower() if ct_eff_discord else None

        is_other_claim = False
        if current_owner_id is not None:
            if my_ct_id is None or current_owner_id != my_ct_id:
                is_other_claim = True
        else:
            claim_username = ct_eff_discord_clean or ct_discord_clean
            if claim_username is not None:
                if my_discord_clean is None or claim_username != my_discord_clean:
                    is_other_claim = True

        if is_other_claim:
            action_str = "claim" if is_tracked else "un-claim"
            claim_username = ct_eff_discord_clean or ct_discord_clean
            logging.warning(f"[CHEESE_DEBUG] Aborting {action_str} for pos {ap_position}: Slot is claimed by a different user (owner_id={current_owner_id}, discord={claim_username}).")
            
            if is_tracked:
                room = session.query(TrackedRoom).filter_by(cheese_tracker_id=tracker_id).first()
                if room:
                    local_slot = session.query(UserTrackedSlot).filter_by(
                        user_id=current_user_id_for_thread,
                        room_id=room.id,
                        slot_id=ap_position
                    ).first()
                    
                    if local_slot:
                        logging.info(f"[CHEESE_DEBUG] Collision: Untracking slot {ap_position} locally.")
                        session.delete(local_slot)
                        
                        player_name = f"Slot {ap_position}"
                        try:
                            players = json.loads(room.cached_players_json or '[]')
                            for p in players:
                                if p.get('slot_id') == ap_position:
                                    player_name = p.get('alias') or p.get('name') or player_name
                                    break
                        except (TypeError, json.JSONDecodeError, AttributeError) as err:
                            logging.debug(
                                "[CHEESE_DEBUG] Failed to parse cached players for room %s: %s",
                                room.id,
                                err,
                            )
                        
                        room_alias = room.room_id
                        subscription = session.query(UserRoomSubscription).filter_by(
                            user_id=current_user_id_for_thread,
                            room_id=room.id
                        ).first()
                        if subscription:
                            room_alias = subscription.alias or room_alias
                            
                        try:
                            from firebase_admin import messaging
                            from .models import Device
                            from . import get_firebase_app
                            
                            get_firebase_app()
                            devices = session.query(Device).filter_by(user_id=current_user_id_for_thread).all()
                            if devices:
                                tokens = [d.fcm_token for d in devices]
                                messages = [
                                    messaging.Message(
                                        notification=messaging.Notification(
                                            title="Slot Sync Conflict",
                                            body=f"Slot '{player_name}' in room '{room_alias}' is already claimed by another user on Cheese Tracker. Untracked slot."
                                        ),
                                        token=token,
                                        android=messaging.AndroidConfig(priority='high')
                                    )
                                    for token in tokens
                                ]
                                if notifications_outbox is not None:
                                    notifications_outbox.append((tokens, messages))
                                else:
                                    messaging.send_each(messages)
                                    logging.info(f"[CHEESE_DEBUG] Sent collision push notification immediately to user {current_user_id_for_thread}")
                        except Exception as p_err:
                            logging.error(f"[CHEESE_DEBUG] Failed to queue collision push: {p_err}")
            return

        # 4. Prepare URL and Payload
        url = f"{CHEESE_BASE_URL}/tracker/{tracker_id}/game/{cheese_game_id}"
        payload = game_object.copy()
        
        if is_tracked:
            payload['claimed_by_ct_user_id'] = my_ct_id
            payload['discord_username'] = None if my_ct_id is not None else my_discord
            payload['availability_status'] = "claimed"
        else:
            payload['claimed_by_ct_user_id'] = None
            payload['discord_username'] = None
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
            logging.debug(f"[CHEESE_DEBUG] Success for pos {ap_position} (game {cheese_game_id})")
            
            if is_tracked and my_ct_id is None:
                response_data = response.json()
                new_ct_id = response_data.get('claimed_by_ct_user_id')
                if new_ct_id:
                    logging.info(f"[CHEESE_DEBUG] LEARNED new ct_user_id: {new_ct_id}")
                    thread_user = session.query(User).filter_by(id=current_user_id_for_thread).first()
                    if thread_user:
                        thread_user.cheese_user_id = new_ct_id
                        # We do NOT commit here; we let the parent worker commit once at the end
        else:
            logging.warning(f"[CHEESE_DEBUG] Failed to set pos {ap_position} (game {cheese_game_id}): {response.status_code} {response.text}")

    except Exception as e:
        logging.error(f"[CHEESE_DEBUG] Error pushing pos {ap_position}: {e}", exc_info=True)

def update_tracker_visibility(app, user_id, cheese_tracker_id, visibility):
    """
    Sets the dashboard visibility override for a specific tracker.
    """
    with app.app_context():
        session = Session()
        try:
            user = session.query(User).get(user_id)
            if not user or not user.cheese_api_key:
                return

            api_key = decrypt_api_key(user.cheese_api_key)
            if not api_key:
                return

            headers = get_cheese_headers()
            headers["Authorization"] = f"Bearer {api_key}"
            
            url = f"{CHEESE_BASE_URL}/tracker/{cheese_tracker_id}/dashboard_override"
            payload = {"visibility": visibility}
            
            resp = requests.put(url, json=payload, headers=headers, timeout=10)
            
            if resp.status_code not in [200, 204]:
                logging.warning(f"[CHEESE_VISIBILITY] Failed to set visibility {visibility} for {cheese_tracker_id}: {resp.status_code}")
            else:
                logging.info(f"[CHEESE_VISIBILITY] Set visibility={visibility} for tracker {cheese_tracker_id} (User {user_id})")

        except Exception as e:
            logging.error(f"[CHEESE_VISIBILITY] Error updating visibility: {e}", exc_info=True)
        finally:
            Session.remove()