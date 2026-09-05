import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import threading
import os
import json
import time
import re
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone

from . import Session
from .models import (
    User, TrackedRoom, UserRoomSubscription, UserTrackedSlot, CheeseDismissedTracker
)
from .api import token_required, log_api_call, handle_db_errors
from .encryption import encrypt_api_key, decrypt_api_key
from .utils import (
    get_cheese_headers, extract_ap_room_id,
    TRACK_MODE_PLAY, TRACK_MODE_WATCH, normalize_track_mode,
    CHEESE_LINK_NONE, CHEESE_LINK_LINKED, normalize_cheese_link
)

load_dotenv()

bp = Blueprint('api_cheese', __name__)

CHEESE_BASE_URL = os.environ.get('CHEESE_BASE_URL', 'https://cheesetrackers.theincrediblewheelofchee.se/api')
CHEESE_DELAY = 60.0

# Cheese Tracker is slow often enough that a single read timeout was losing slot
# claims outright: the local rows commit, the push dies in a log line, and nothing
# reconciles -- the app says Playing while the slot stays open on Cheese. Every
# Cheese call goes through one session with a small retry budget, which also reuses
# connections instead of opening a new one per request. See #304.
#
# POST is deliberately absent from the retried methods: creating a tracker is not
# idempotent. The retried verbs are, and the PUT that claims a slot additionally
# carries an x-if-owner-is precondition, so a retry after a read timeout that did
# land fails the precondition rather than overwriting someone else's claim.
_CHEESE_RETRY = Retry(
    total=2,
    connect=2,
    read=2,
    status=2,
    status_forcelist=(500, 502, 503, 504),
    allowed_methods=frozenset(("GET", "PUT", "DELETE", "HEAD", "OPTIONS")),
    backoff_factor=0.5,
    raise_on_status=False,
)

def _build_cheese_session():
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=_CHEESE_RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

# Shared across request threads and the background push worker. Safe because
# nothing mutates it -- headers are passed per call, and urllib3's pool is
# thread-safe.
_cheese_session = _build_cheese_session()
    
def _fetch_tracker_details(req_session, tracker_ids):
    """
    Fetch the full payload for each tracker, keyed by id.

    A tracker that fails to fetch is simply absent from the result, and every
    caller treats absence as "no news" rather than as evidence of a change.
    """
    details = {}
    for ct_id in tracker_ids:
        time.sleep(0.5)
        try:
            resp = req_session.get(f"{CHEESE_BASE_URL}/tracker/{ct_id}", timeout=10)
            if not resp.ok:
                logging.warning(f"[CHEESE_DEBUG] Tracker {ct_id} detail returned {resp.status_code}.")
                continue
            payload = resp.json()
            # Anything that is not a JSON object is not a tracker. Letting one
            # through would take down the whole sync on the first attribute
            # access, losing the reconciliation for every other room with it.
            if not isinstance(payload, dict):
                logging.warning(f"[CHEESE_DEBUG] Tracker {ct_id} detail was not an object; ignoring it.")
                continue
            details[ct_id] = payload
        except Exception as e:
            logging.error(f"[CHEESE_DEBUG] Failed to fetch details for {ct_id}: {e}")
    return details


def _apply_tracker_payload(room, full_data):
    """Refresh a room's cached Cheese payload from a tracker detail response."""
    room.cached_cheese_json = json.dumps(full_data)
    if full_data.get('updated_at'):
        try:
            room.cheese_updated_at = datetime.fromisoformat(
                full_data.get('updated_at').replace('Z', '+00:00')
            )
        except ValueError:
            pass


def _reconcile_claims(session, user, room, full_data, my_cheese_id, discord_username, stats):
    """
    Bring one linked room's slot claims into line with what Cheese reports.

    Cheese owns claims -- they are shared state between everyone in the room, so
    the app cannot decide them unilaterally. What the app owns is alerts, and
    those are never withdrawn here: a slot Cheese does not confirm is demoted to
    watch, never untracked.

    Returns the user's possibly-updated Cheese id, which the discord-username
    fallback can discover.
    """
    games = full_data.get('games', [])

    # A tracker with no games carries no ownership information, so it is not
    # evidence that anything is unclaimed. Without this, an `ok` response with an
    # empty games array demotes every claim in the room in one pass -- a
    # brand-new tracker with no games yet is enough to trigger it.
    if not games:
        logging.warning(
            f"[CHEESE_DEBUG] Tracker {room.cheese_tracker_id} returned no games; "
            f"skipping claim reconciliation for room {room.id}."
        )
        return my_cheese_id

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

    slots_found.discard(None)

    existing_slots = session.query(UserTrackedSlot).filter_by(
        user_id=user.id, room_id=room.id
    ).all()
    existing_by_id = {s.slot_id: s for s in existing_slots}

    # Connecting mid-async must not cost the user slots they were already
    # tracking. Anything Cheese does not confirm as theirs is demoted to watch
    # instead: alerts survive, the claim does not, and the demotion is
    # reversible from the app.
    for slot_id, existing in existing_by_id.items():
        if slot_id in slots_found:
            continue
        if normalize_track_mode(existing.track_mode) != TRACK_MODE_PLAY:
            continue
        logging.info(
            f"[CHEESE_DEBUG] Demoting slot {slot_id} in room {room.id} to watch "
            f"(not claimed by user {user.id} on Cheese)."
        )
        existing.track_mode = TRACK_MODE_WATCH
        stats['demoted'] += 1

    for slot_id in slots_found:
        if existing_by_id.get(slot_id) is None:
            # notify_finished is deliberately left NULL so the slot inherits
            # User.notify_finished_default and keeps following it. Stamping the
            # default in here would write a permanent per-slot override, so
            # CT-created slots would stop tracking the global setting while
            # picker-created ones kept following it.
            session.add(UserTrackedSlot(
                user_id=user.id,
                room_id=room.id,
                slot_id=slot_id,
                track_mode=TRACK_MODE_PLAY,
                # A slot Cheese says the user owns is one they are playing, so it
                # earns their auto-apply milestone templates like any other.
                auto_apply_pending=True,
            ))
            stats['slots_synced'] += 1
        # Watch is sticky: a slot the user already tracks is left in whatever
        # mode they put it in, even when Cheese still shows them as the owner.
        # That happens when a play -> watch release failed to land, and silently
        # re-claiming would revert an explicit choice. The picker shows "Claimed
        # by you on Cheese Tracker" so they can switch back deliberately.

    return my_cheese_id


def setup_cheese_user_task(app, user_id):
    """
    Reconcile the rooms this user has linked to Cheese Tracker.

    The app owns the room library, so this task never adds a room and never
    removes one. It refreshes the cached tracker payload for linked rooms,
    reconciles their slot claims, and flags a linked room that has fallen off
    the user's Cheese dashboard so the app can say so. Trackers the app does not
    have are offered through GET /integrations/cheese/available instead of being
    imported. See #323.

    Only linked trackers are fetched in detail, so the cost of a sync scales with
    what the user actually mirrors rather than with the size of their dashboard.
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

            # The set of trackers worth a detail request: the ones this user
            # asked us to mirror. Deliberately not filtered by dashboard
            # membership -- a linked room the user hid on Cheese still gets its
            # claims reconciled, it is just flagged as unlisted below.
            linked_tracker_ids = {
                ct_id for (ct_id,) in session.query(TrackedRoom.cheese_tracker_id)
                .join(UserRoomSubscription, UserRoomSubscription.room_id == TrackedRoom.id)
                .filter(
                    UserRoomSubscription.user_id == user.id,
                    UserRoomSubscription.cheese_link == CHEESE_LINK_LINKED,
                    TrackedRoom.cheese_tracker_id.isnot(None),
                ).all()
            }

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

                # 3. Fetch details for the linked trackers only.
                details_by_ct_id = _fetch_tracker_details(req_session, linked_tracker_ids)

            # Every tracker the dashboard knows about, hidden ones included.
            # Visibility decides whether a tracker is worth *suggesting*; it says
            # nothing about whether a room the user already linked is still real.
            dashboard_tracker_ids = {
                t.get('tracker_id') for t in trackers_list if t.get('tracker_id')
            }

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

            stats = {'refreshed': 0, 'slots_synced': 0, 'demoted': 0, 'unlisted': 0, 'relisted': 0}

            linked_subs = session.query(UserRoomSubscription, TrackedRoom)\
                .join(TrackedRoom, UserRoomSubscription.room_id == TrackedRoom.id)\
                .filter(
                    UserRoomSubscription.user_id == user.id,
                    UserRoomSubscription.cheese_link == CHEESE_LINK_LINKED,
                ).all()

            for sub, room in linked_subs:
                ct_id = room.cheese_tracker_id
                if not ct_id:
                    # Linked but never pushed. The healing phase below owns it.
                    continue

                full_data = details_by_ct_id.get(ct_id)
                if full_data is not None:
                    _apply_tracker_payload(room, full_data)
                    stats['refreshed'] += 1
                    my_cheese_id = _reconcile_claims(
                        session, user, room, full_data, my_cheese_id, discord_username, stats
                    )

                # Dashboard presence is a flag, never a deletion. An empty
                # dashboard is not evidence of anything -- one thin response used
                # to be enough to wipe a whole library (#323) -- so it is ignored
                # outright.
                if not dashboard_tracker_ids:
                    continue

                if ct_id in dashboard_tracker_ids:
                    if sub.cheese_unlisted_at is not None:
                        sub.cheese_unlisted_at = None
                        stats['relisted'] += 1
                elif sub.cheese_unlisted_at is None:
                    logging.info(
                        f"[CHEESE_DEBUG] Room {room.id} is linked but no longer on user "
                        f"{user.id}'s Cheese dashboard; flagging it."
                    )
                    sub.cheese_unlisted_at = datetime.utcnow()
                    stats['unlisted'] += 1

            session.commit()
            logging.info(f"[CHEESE_DEBUG] Sync loop complete. Stats: {stats}")

            try:
                # HEALING PHASE: Pushing linked-but-unpushed rooms to Cheese.
                # Scoped to cheese_link, so a room the user keeps private to the
                # app is never published on their behalf.
                from sqlalchemy.orm import selectinload
                orphaned_subs = session.query(UserRoomSubscription)\
                    .options(selectinload(UserRoomSubscription.room))\
                    .join(TrackedRoom)\
                    .filter(UserRoomSubscription.user_id == user.id)\
                    .filter(UserRoomSubscription.cheese_link == CHEESE_LINK_LINKED)\
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
                    logging.info(f"[CHEESE_DEBUG] Found {len(rooms_to_push)} linked rooms to push. Closing DB session for network operations.")

                    # Close the session before starting the synchronous push loop
                    # This ensures push_new_room_to_cheese (which opens its own session)
                    # doesn't conflict with the current one.
                    Session.remove()

                    # Execute network calls safely
                    for data in rooms_to_push:
                        logging.info(f"[CHEESE_DEBUG] Pushing linked room: {data['room_id']}")
                        push_new_room_to_cheese(
                            app,
                            user_id,
                            data['tracker_url'],
                            data['room_id'],
                            data['room_url'],
                            data['alias']
                        )
                else:
                    logging.info("[CHEESE_DEBUG] No linked rooms waiting to be pushed.")

            except Exception as e:
                logging.error(f"[CHEESE_DEBUG] Error during healing phase: {e}", exc_info=True)

            # --- RE-FETCH USER TO UNLOCK ---
            logging.info(f"[CHEESE_DEBUG] Sync task finished. Unlocking user {user_id}...")
            session = Session()
            fresh_user = session.query(User).get(user_id)
            if fresh_user:
                fresh_user.is_syncing_cheese = False
                fresh_user.cheese_last_sync = datetime.utcnow()
                # Surfaced by the app as a post-sync summary so a mid-async
                # connect never silently changes slots out from under the user.
                fresh_user.cheese_last_sync_demoted = stats.get('demoted', 0)
                fresh_user.cheese_last_sync_unlisted = stats.get('unlisted', 0)
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

        test_resp = _cheese_session.get(f"{CHEESE_BASE_URL}/user/self", headers=test_headers, timeout=10)
        
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



def _fetch_dashboard(api_key):
    """
    Read the user's Cheese dashboard. One request, no per-tracker detail.

    Returns the tracker list, or None when the call failed -- which every caller
    must treat as "no news", never as an empty dashboard.
    """
    headers = get_cheese_headers()
    headers['Authorization'] = f"Bearer {api_key}"
    try:
        resp = _cheese_session.get(f"{CHEESE_BASE_URL}/dashboard/tracker", headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logging.error(f"[CHEESE_DEBUG] Dashboard fetch failed: {e}")
        return None


@bp.route('/available', methods=['GET'])
@handle_db_errors
@log_api_call
@token_required
def list_available_cheese_rooms(current_user):
    """
    Rooms on the user's Cheese dashboard that the app does not have.

    These are offered, never imported. The app shows them as suggestions the
    user accepts or dismisses, which is the whole difference between Cheese
    proposing a room and Cheese writing one into somebody's library (#323).
    """
    if not current_user.cheese_api_key:
        return jsonify({'error': 'Not connected to Cheese Tracker.'}), 400

    api_key = decrypt_api_key(current_user.cheese_api_key)
    if not api_key:
        return jsonify({'error': 'Could not read your stored Cheese key.'}), 500

    trackers = _fetch_dashboard(api_key)
    if trackers is None:
        return jsonify({'error': 'Could not reach Cheese Tracker.'}), 502

    session = Session()

    known_tracker_ids = {
        ct_id for (ct_id,) in session.query(TrackedRoom.cheese_tracker_id)
        .join(UserRoomSubscription, UserRoomSubscription.room_id == TrackedRoom.id)
        .filter(
            UserRoomSubscription.user_id == current_user.id,
            TrackedRoom.cheese_tracker_id.isnot(None),
        ).all()
    }

    dismissed_ids = {
        ct_id for (ct_id,) in session.query(CheeseDismissedTracker.cheese_tracker_id)
        .filter(CheeseDismissedTracker.user_id == current_user.id).all()
    }

    available = []
    for tracker in trackers:
        ct_id = tracker.get('tracker_id')
        if not ct_id or ct_id in known_tracker_ids or ct_id in dismissed_ids:
            continue
        # A tracker the user hid on their Cheese dashboard is not a room they
        # are asking us to suggest.
        if tracker.get('dashboard_override_visibility') is False:
            continue

        available.append({
            'cheese_tracker_id': ct_id,
            'title': tracker.get('title') or 'Unknown Room',
            'room_link': tracker.get('room_link'),
            'last_activity': tracker.get('last_activity') or tracker.get('updated_at'),
        })

    return jsonify({'available': available, 'count': len(available)})


@bp.route('/available/dismiss', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def dismiss_available_cheese_rooms(current_user):
    """Stop offering these trackers. Reversible by importing them later."""
    data = request.json or {}
    tracker_ids = data.get('cheese_tracker_ids')
    if not isinstance(tracker_ids, list) or not tracker_ids:
        return jsonify({'error': 'cheese_tracker_ids must be a non-empty list.'}), 400

    session = Session()
    dismissed = 0
    for ct_id in tracker_ids:
        if not isinstance(ct_id, str) or not ct_id.strip():
            continue
        ct_id = ct_id.strip()
        exists = session.query(CheeseDismissedTracker).filter_by(
            user_id=current_user.id, cheese_tracker_id=ct_id
        ).first()
        if exists:
            continue
        session.add(CheeseDismissedTracker(user_id=current_user.id, cheese_tracker_id=ct_id))
        dismissed += 1

    session.commit()
    return jsonify({'message': 'Dismissed.', 'dismissed': dismissed})


@bp.route('/available/import', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def import_available_cheese_rooms(current_user):
    """
    Add the named Cheese trackers to the user's library, linked.

    This is the only path that creates a room from Cheese, and it only runs
    because somebody tapped Add. The claim reconciliation that used to happen
    for every dashboard tracker on every sync happens here once, for the rooms
    the user chose.
    """
    data = request.json or {}
    tracker_ids = data.get('cheese_tracker_ids')
    if not isinstance(tracker_ids, list) or not tracker_ids:
        return jsonify({'error': 'cheese_tracker_ids must be a non-empty list.'}), 400

    if not current_user.cheese_api_key:
        return jsonify({'error': 'Not connected to Cheese Tracker.'}), 400

    api_key = decrypt_api_key(current_user.cheese_api_key)
    if not api_key:
        return jsonify({'error': 'Could not read your stored Cheese key.'}), 500

    wanted = {t.strip() for t in tracker_ids if isinstance(t, str) and t.strip()}
    if not wanted:
        return jsonify({'error': 'cheese_tracker_ids must be a non-empty list.'}), 400

    trackers = _fetch_dashboard(api_key)
    if trackers is None:
        return jsonify({'error': 'Could not reach Cheese Tracker.'}), 502

    by_id = {t.get('tracker_id'): t for t in trackers if t.get('tracker_id')}
    missing = sorted(wanted - set(by_id))

    with requests.Session() as req_session:
        req_session.headers.update(get_cheese_headers())
        req_session.headers['Authorization'] = f"Bearer {api_key}"
        details = _fetch_tracker_details(req_session, wanted & set(by_id))

    session = Session()
    user = session.merge(current_user)
    my_cheese_id = user.cheese_user_id
    discord_username = user.discord_username.strip().lower() if user.discord_username else None

    stats = {'imported': 0, 'slots_synced': 0, 'demoted': 0}
    failed = []

    for ct_id in sorted(wanted & set(by_id)):
        full_data = details.get(ct_id)
        if full_data is None:
            failed.append(ct_id)
            continue

        meta = by_id[ct_id]
        room_link = meta.get('room_link')
        title = meta.get('title') or 'Unknown Room'

        room = session.query(TrackedRoom).filter_by(cheese_tracker_id=ct_id).first()

        if not room and room_link:
            ap_room_id = extract_ap_room_id(room_link)
            if ap_room_id:
                room = session.query(TrackedRoom).filter_by(room_id=ap_room_id).first()
                if room and not room.cheese_tracker_id:
                    room.cheese_tracker_id = ct_id
                    logging.info(f"[CHEESE_IMPORT] Linked existing AP room {ap_room_id} to Cheese ID {ct_id}")

        if not room:
            ap_room_id_extracted = extract_ap_room_id(room_link) or "PENDING_DISCOVERY_" + ct_id[:8]
            hostname = "archipelago.gg"
            try:
                if room_link:
                    hostname = urlparse(room_link).hostname or "archipelago.gg"
            except Exception:
                pass

            room = TrackedRoom(
                room_id=ap_room_id_extracted,
                hostname=hostname,
                cheese_tracker_id=ct_id,
                cached_full_address=hostname,
            )
            session.add(room)
            session.flush()
            logging.info(f"[CHEESE_IMPORT] Created room {ap_room_id_extracted} for tracker {ct_id}")

        _apply_tracker_payload(room, full_data)

        sub = session.query(UserRoomSubscription).filter_by(
            user_id=user.id, room_id=room.id
        ).first()
        if not sub:
            sub = UserRoomSubscription(
                user_id=user.id,
                room_id=room.id,
                alias=title,
                icon_name='cheese',
                cheese_link=CHEESE_LINK_LINKED,
            )
            session.add(sub)
            session.flush()
            stats['imported'] += 1
        else:
            # Already tracked, so this is really "start mirroring it".
            sub.cheese_link = CHEESE_LINK_LINKED
            sub.is_archived = False
        sub.cheese_unlisted_at = None

        my_cheese_id = _reconcile_claims(
            session, user, room, full_data, my_cheese_id, discord_username, stats
        )

        # Accepting a suggestion answers the question a dismissal was hiding.
        session.query(CheeseDismissedTracker).filter_by(
            user_id=user.id, cheese_tracker_id=ct_id
        ).delete()

    session.commit()

    if missing:
        logging.warning(f"[CHEESE_IMPORT] User {current_user.id} asked for trackers not on their dashboard: {missing}")

    return jsonify({
        'message': f"Added {stats['imported']} room(s).",
        'imported': stats['imported'],
        'slots_synced': stats['slots_synced'],
        'demoted': stats['demoted'],
        'failed': failed + missing,
    })


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
        response_post = _cheese_session.post(f"{CHEESE_BASE_URL}/tracker", json=payload, headers=headers, timeout=10)

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
        response_get = _cheese_session.get(f"{CHEESE_BASE_URL}/tracker/{cheese_tracker_id}", headers=headers, timeout=10)
        
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
        response_put = _cheese_session.put(f"{CHEESE_BASE_URL}/tracker/{cheese_tracker_id}", json=put_payload, headers=put_headers, timeout=10)
        
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
                    # Watch slots are never claimed on Cheese. The picker can now
                    # offer Watching before the room is linked (#314), and this
                    # catch-up runs about two minutes after the room is added --
                    # comfortably after the user has made that choice. Claiming
                    # everything found here would convert an explicit "Watching"
                    # into a real claim on their Cheese account, and it would not
                    # heal: the local mode stays watch, so the next sync leaves it
                    # alone while the claim stays held. Anything not explicitly
                    # watch is still claimed, which keeps the old behaviour for
                    # every other value.
                    slots_to_claim = session.query(UserTrackedSlot.slot_id).filter(
                        UserTrackedSlot.user_id == user_id,
                        UserTrackedSlot.room_id == local_room.id,
                        UserTrackedSlot.track_mode != TRACK_MODE_WATCH,
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
            # One tracker fetch for the whole batch. This used to sit inside send_state,
            # so an N-slot push made N full tracker downloads -- N chances to hit the read
            # timeout that silently drops a claim, which is why large rooms were worst
            # affected. See #304.
            try:
                detail_resp = _cheese_session.get(
                    f"{CHEESE_BASE_URL}/tracker/{tracker_id}",
                    headers=base_headers,
                    timeout=10
                )
                if not detail_resp.ok:
                    logging.warning(f"[CHEESE_DEBUG_WORKER] Tracker {tracker_id} fetch returned {detail_resp.status_code}; no slots pushed.")
                    return
                tracker_details = detail_resp.json()
            except Exception as fetch_err:
                logging.error(f"[CHEESE_DEBUG_WORKER] Could not read tracker {tracker_id}; no slots pushed: {fetch_err}", exc_info=True)
                return

            # Process removals
            for slot_id in removed_slots:
                send_state(session, app, slot_id, False, user_id, my_ct_id, tracker_id, base_headers, tracker_details, notifications_outbox)
            
            # Process additions
            for slot_id in added_slots:
                send_state(session, app, slot_id, True, user_id, my_ct_id, tracker_id, base_headers, tracker_details, notifications_outbox)

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

            # A room the user has unlinked keeps its tracker id -- unlinking does
            # not delete anything on Cheese -- so the id alone is not permission
            # to write. The link is. See #323.
            sub = temp_session.query(UserRoomSubscription.cheese_link).filter_by(
                user_id=user_id, room_id=room_db_id
            ).first()
            if not sub or normalize_cheese_link(sub.cheese_link) != CHEESE_LINK_LINKED:
                logging.info(
                    f"[CHEESE_DEBUG] Aborting: room {room_db_id} is not linked to Cheese for user {user_id}."
                )
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

def send_state(session, app, ap_position, is_tracked, current_user_id_for_thread, initial_ct_id, tracker_id, base_headers, tracker_details, notifications_outbox=None):
    """
    Helper function to send the state to Cheese Tracker.
    """
    try:
        my_ct_id = initial_ct_id

        # 1. `tracker_details` is the caller's snapshot of the tracker, taken once for
        # the whole batch. Each position is written independently, so one slot's write
        # does not invalidate another's entry. A third party claiming the slot between
        # the snapshot and the PUT is caught by the x-if-owner-is precondition below,
        # which fails the write rather than overwriting them.
        games = tracker_details.get('games', [])

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
        updated_at_timestamp = tracker_details.get('updated_at')
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
                    
                    # Demote to watch rather than deleting. The user keeps their
                    # alerts, thresholds and per-slot prefs; they just stop
                    # owning the slot on Cheese. Losing a claim is never a
                    # reason to throw away tracking state.
                    if local_slot and normalize_track_mode(local_slot.track_mode) == TRACK_MODE_PLAY:
                        logging.info(f"[CHEESE_DEBUG] Collision: Demoting slot {ap_position} to watch.")
                        local_slot.track_mode = TRACK_MODE_WATCH

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
                                            title="Slot Already Claimed",
                                            body=f"'{player_name}' in '{room_alias}' is claimed by someone else on Cheese Tracker. Switched to Watching — you'll still get alerts."
                                        ),
                                        token=token,
                                        android=messaging.AndroidConfig(
                                            priority='high',
                                            notification=messaging.AndroidNotification(
                                                channel_id='channel_general'
                                            )
                                        ),
                                        data={
                                            'notification_type': 'conflict',
                                            'channel_id': 'channel_general'
                                        }
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
            # Apply the user's default ping preference at claim time (mirrors CT's
            # web UI, which seeds discord_ping from the user's default on claim).
            # Null default leaves whatever the slot already had.
            default_ping = getattr(user, 'cheese_default_ping', None)
            if default_ping:
                payload['discord_ping'] = default_ping
        else:
            payload['claimed_by_ct_user_id'] = None
            payload['discord_username'] = None
            # Align with CT's web UI on unclaim: availability returns to "open"
            # and the ping preference resets to "never".
            payload['availability_status'] = "open"
            payload['discord_ping'] = "never"
        
        # 5. Prepare final headers
        put_headers = base_headers.copy()
        owner_precondition = {
            "claimed_by_ct_user_id": game_object.get('claimed_by_ct_user_id'),
            "discord_username": game_object.get('discord_username')
        }
        put_headers['x-if-owner-is'] = json.dumps(owner_precondition)
        
        # 6. Send the update
        response = _cheese_session.put(url, json=payload, headers=put_headers, timeout=5)
        
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

# Progression statuses that, when set, should also stamp last_checked (mirrors
# CT's web UI: setting BK/Soft BK updates "last checked").
_CHEESE_BK_STATUSES = {'bk', 'soft_bk'}


def apply_cheese_slot_update(app, user_id, room_db_id, slot_id, updates):
    """
    Synchronously applies a partial update to a single game (slot) on Cheese
    Tracker and splices the result back into the local cache.

    `updates` is a dict that may contain any of:
        notes (str), progression_status (str), completion_status (str),
        discord_ping (str), touch_last_checked (bool)

    Returns a result dict:
        {'status': 'ok', 'game': <updated game dict>, 'global_ping_policy': ...}
        {'status': 'not_connected' | 'no_tracker' | 'not_tracked' | 'watching' |
                   'not_found' | 'forbidden' | 'conflict' | 'error'}
    """
    # === 1. PRE-FLIGHT (DB) ===
    api_key = None
    tracker_id = None
    my_ct_id = None
    my_discord_clean = None
    with app.app_context():
        session = Session()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if not user or not user.cheese_api_key:
                return {'status': 'not_connected'}

            room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
            if not room or not room.cheese_tracker_id:
                return {'status': 'no_tracker'}

            # Unlinking a room leaves its tracker id in place, so writes are
            # gated on the link rather than on the id. See #323.
            sub = session.query(UserRoomSubscription.cheese_link).filter_by(
                user_id=user_id, room_id=room_db_id
            ).first()
            if not sub or normalize_cheese_link(sub.cheese_link) != CHEESE_LINK_LINKED:
                return {'status': 'no_tracker'}

            local_slot = session.query(UserTrackedSlot).filter_by(
                user_id=user_id, room_id=room_db_id, slot_id=slot_id
            ).first()
            if not local_slot:
                return {'status': 'not_tracked'}

            # Watch slots are read-only on Cheese by definition. The remote
            # ownership check below would usually catch this too, but not when
            # the slot happens to be unclaimed -- editing someone else's
            # unclaimed slot is still not ours to do.
            if normalize_track_mode(local_slot.track_mode) != TRACK_MODE_PLAY:
                return {'status': 'watching'}

            api_key = decrypt_api_key(user.cheese_api_key)
            if not api_key:
                logging.error(f"[CHEESE_SLOT] Failed to decrypt key for user {user_id}.")
                return {'status': 'error'}

            tracker_id = room.cheese_tracker_id
            my_ct_id = user.cheese_user_id
            my_discord_clean = user.discord_username.strip().lower() if user.discord_username else None
        finally:
            Session.remove()

    # === 2. NETWORK PHASE (no DB session held) ===
    base_headers = get_cheese_headers()
    base_headers["Authorization"] = f"Bearer {api_key}"

    try:
        detail_resp = _cheese_session.get(f"{CHEESE_BASE_URL}/tracker/{tracker_id}", headers=base_headers, timeout=10)
        if not detail_resp.ok:
            logging.warning(f"[CHEESE_SLOT] Failed to fetch tracker {tracker_id}: {detail_resp.status_code}")
            return {'status': 'error'}

        details = detail_resp.json()
        games = details.get('games', [])

        game_object = None
        for game in games:
            if game.get('position') == slot_id:
                game_object = game
                break

        if not game_object:
            return {'status': 'not_found'}

        # Ownership check (mirrors send_state): the current user must own the slot.
        remote_owner_id = game_object.get('claimed_by_ct_user_id')
        if remote_owner_id is not None:
            is_mine = (my_ct_id is not None and remote_owner_id == my_ct_id)
        else:
            claim_discord = game_object.get('effective_discord_username') or game_object.get('discord_username')
            claim_discord_clean = claim_discord.strip().lower() if claim_discord else None
            is_mine = (claim_discord_clean is not None and my_discord_clean is not None
                       and claim_discord_clean == my_discord_clean)

        if not is_mine:
            logging.warning(f"[CHEESE_SLOT] User {user_id} attempted to edit unowned slot {slot_id} in {tracker_id}.")
            return {'status': 'forbidden'}

        cheese_game_id = game_object.get('id')
        if not cheese_game_id:
            logging.error(f"[CHEESE_SLOT] Game object for pos {slot_id} has no id.")
            return {'status': 'error'}

        # Build the PUT payload from the current object, applying only the deltas.
        payload = game_object.copy()
        now_iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        if 'notes' in updates:
            payload['notes'] = updates['notes'] or ''
        if 'discord_ping' in updates:
            payload['discord_ping'] = updates['discord_ping']
        if 'completion_status' in updates:
            payload['completion_status'] = updates['completion_status']
        if 'progression_status' in updates:
            payload['progression_status'] = updates['progression_status']
            # Setting a BK status also refreshes last_checked, matching CT's UI.
            if updates['progression_status'] in _CHEESE_BK_STATUSES:
                payload['last_checked'] = now_iso
        # "Still BK": explicit request to refresh last_checked without other changes.
        if updates.get('touch_last_checked'):
            payload['last_checked'] = now_iso

        # x-if-owner-is guard: fail (412) if the claim changed under us.
        put_headers = base_headers.copy()
        put_headers['x-if-owner-is'] = json.dumps({
            "claimed_by_ct_user_id": game_object.get('claimed_by_ct_user_id'),
            "discord_username": game_object.get('discord_username')
        })

        url = f"{CHEESE_BASE_URL}/tracker/{tracker_id}/game/{cheese_game_id}"
        put_resp = _cheese_session.put(url, json=payload, headers=put_headers, timeout=10)

        if put_resp.status_code == 412:
            return {'status': 'conflict'}
        if put_resp.status_code not in (200, 204):
            logging.warning(f"[CHEESE_SLOT] PUT failed for game {cheese_game_id}: {put_resp.status_code} {put_resp.text}")
            return {'status': 'error'}

        # The response body is the authoritative updated game (CT may force-upgrade
        # completion_status). Fall back to our payload if the body is empty (204).
        updated_game = payload
        try:
            if put_resp.content:
                body = put_resp.json()
                if isinstance(body, dict):
                    updated_game = body
        except Exception:
            updated_game = payload

    except requests.exceptions.RequestException as e:
        logging.error(f"[CHEESE_SLOT] Network error updating slot {slot_id}: {e}")
        return {'status': 'error'}
    except Exception as e:
        logging.error(f"[CHEESE_SLOT] Unexpected error updating slot {slot_id}: {e}", exc_info=True)
        return {'status': 'error'}

    # === 3. DB PHASE: splice updated game into cached_cheese_json ===
    with app.app_context():
        session = Session()
        try:
            room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
            if room and room.cached_cheese_json:
                try:
                    cached = json.loads(room.cached_cheese_json)
                    if isinstance(cached, dict) and isinstance(cached.get('games'), list):
                        for idx, g in enumerate(cached['games']):
                            if g.get('position') == slot_id:
                                # Preserve computed fields from the cache that the
                                # game PUT response may not include.
                                merged = g.copy()
                                merged.update(updated_game)
                                cached['games'][idx] = merged
                                updated_game = merged
                                break
                        room.cached_cheese_json = json.dumps(cached)
                        session.commit()
                except (json.JSONDecodeError, TypeError) as e:
                    logging.warning(f"[CHEESE_SLOT] Could not splice cache for room {room_db_id}: {e}")
                    session.rollback()
        except Exception as e:
            session.rollback()
            logging.error(f"[CHEESE_SLOT] DB splice failed: {e}", exc_info=True)
        finally:
            Session.remove()

    return {
        'status': 'ok',
        'game': updated_game,
        'global_ping_policy': details.get('global_ping_policy')
    }


def refresh_tracker_cache(app, user_id, room_db_id):
    """
    On-demand refresh of a single room's Cheese Tracker cache. Performs an
    authenticated GET of the tracker and runs the same processing the background
    poller uses, so the local cache reflects Cheese Tracker's current state
    immediately instead of waiting for the next ~5 minute poll cycle.

    Returns {'status': 'ok'} or {'status': 'not_connected'|'no_tracker'|'error'}.
    """
    api_key = None
    tracker_id = None
    with app.app_context():
        session = Session()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if not user or not user.cheese_api_key:
                return {'status': 'not_connected'}
            room = session.query(TrackedRoom).filter_by(id=room_db_id).first()
            if not room or not room.cheese_tracker_id:
                return {'status': 'no_tracker'}
            api_key = decrypt_api_key(user.cheese_api_key)
            if not api_key:
                logging.error(f"[CHEESE_REFRESH] Failed to decrypt key for user {user_id}.")
                return {'status': 'error'}
            tracker_id = room.cheese_tracker_id
        finally:
            Session.remove()

    headers = get_cheese_headers()
    headers['Authorization'] = f"Bearer {api_key}"
    try:
        resp = _cheese_session.get(f"{CHEESE_BASE_URL}/tracker/{tracker_id}", headers=headers, timeout=10)
        if not resp.ok:
            logging.warning(f"[CHEESE_REFRESH] Fetch failed for {tracker_id}: {resp.status_code}")
            return {'status': 'error'}
        data = resp.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"[CHEESE_REFRESH] Network error for {tracker_id}: {e}")
        return {'status': 'error'}
    except Exception as e:
        logging.error(f"[CHEESE_REFRESH] Unexpected error for {tracker_id}: {e}", exc_info=True)
        return {'status': 'error'}

    remote_updated_at = data.get('updated_at')
    if not remote_updated_at:
        logging.warning(f"[CHEESE_REFRESH] Tracker {tracker_id} returned no updated_at.")
        return {'status': 'error'}

    try:
        # Reuse the poller's processing so a manual refresh behaves identically
        # to a poll cycle (cache update + claim reconciliation).
        from app.services.cheese_service import process_cheese_update
        with app.app_context():
            payload = process_cheese_update(room_db_id, data, remote_updated_at)
            _send_demotion_pushes(payload)
    except Exception as e:
        logging.error(f"[CHEESE_REFRESH] Processing failed for room {room_db_id}: {e}", exc_info=True)
        return {'status': 'error'}

    return {'status': 'ok'}


def _send_demotion_pushes(payload):
    """
    Sends the demotion payload process_cheese_update returns.

    A manual refresh reconciles claims for the whole room, not just the caller's
    slots, so it can demote someone else's slot from Playing to Watching. Dropping
    the payload here left that as silent as the poller's unreachable loop was
    before #289 -- the owner would find out by noticing the badge change.

    Failures are logged rather than raised: the refresh itself succeeded, and the
    caller should not see an error because a push did not go out.
    """
    if not payload:
        return

    from app.services.notification_service import send_fcm_notifications

    for user_id, entry in payload.items():
        notifications = entry.get('notifications')
        if not notifications:
            continue
        for platform, tokens in (entry.get('tokens') or {}).items():
            if not tokens:
                continue
            try:
                logging.info(
                    f"[CHEESE_NOTIFY] Refresh sending {len(notifications)} to user {user_id} ({platform})"
                )
                send_fcm_notifications(tokens, notifications, platform=platform)
            except Exception as e:
                logging.error(
                    f"[CHEESE_NOTIFY] Push failed for user {user_id} ({platform}): {e}", exc_info=True
                )


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
            
            resp = _cheese_session.put(url, json=payload, headers=headers, timeout=10)
            
            if resp.status_code not in [200, 204]:
                logging.warning(f"[CHEESE_VISIBILITY] Failed to set visibility {visibility} for {cheese_tracker_id}: {resp.status_code}")
            else:
                logging.info(f"[CHEESE_VISIBILITY] Set visibility={visibility} for tracker {cheese_tracker_id} (User {user_id})")

        except Exception as e:
            logging.error(f"[CHEESE_VISIBILITY] Error updating visibility: {e}", exc_info=True)
        finally:
            Session.remove()