import jwt
import requests
import logging
import uuid
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, current_app, url_for

from .models import User
from . import Session

bp = Blueprint('auth', __name__, url_prefix='/auth')

@bp.route('/guest', methods=['POST'])
def create_guest_user():
    """
    Creates a new anonymous "guest" user and returns a standard JWT.
    """
    session = Session()
    user_id_for_jwt = None
    try:
        guest_uuid = str(uuid.uuid4())
        
        new_user = User(
            discord_id=None,
            discord_username=None,
            discord_avatar_hash=None,
            is_guest=True,
            guest_uuid=guest_uuid
        )
        
        session.add(new_user)
        session.commit()
        
        user_id_for_jwt = new_user.id
        logging.info(f"[AUTH] New guest user created: {new_user.id} (UUID: {guest_uuid})")
        
    except Exception as e:
        session.rollback()
        logging.error(f"[AUTH_ERROR] Database error during guest user creation: {e}", exc_info=True)
        return jsonify({"error": "Could not create guest account."}), 500
    finally:
        Session.remove()

    jwt_id = str(uuid.uuid4())
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(days=30) 

    payload = {
        'user_id': user_id_for_jwt,
        'iat': issued_at,
        'exp': expires_at,
        'jti': jwt_id,
        'type': 'access'
    }
    secret = current_app.config['SECRET_KEY']
    app_token = jwt.encode(payload, secret, algorithm='HS256')

    return jsonify({
        'message': 'Guest access granted!',
        'token': app_token,
        'is_unlimited_pin': False 
    })

@bp.route('/callback', methods=['POST'])
def callback():
    """
    The endpoint the Android app calls after getting an authorization code from Discord.
    This version uses a manual 'requests' call for maximum reliability.
    """
    data = request.json
    code = data.get('code')
    redirect_uri = data.get('redirect_uri')
    code_verifier = data.get('code_verifier')

    if not all([code, redirect_uri, code_verifier]):
        return jsonify({'error': 'Malformed request. Missing required fields.'}), 400

    expected_redirect_uri = current_app.config.get('DISCORD_REDIRECT_URI')
    if redirect_uri != expected_redirect_uri:
        logging.warning(f"[AUTH_WARN] Redirect URI mismatch. Expected '{expected_redirect_uri}', got '{redirect_uri}'.")
        return jsonify({'error': 'Redirect URI mismatch.'}), 400

    token_url = current_app.config['DISCORD_TOKEN_URL']
    client_id = current_app.config['DISCORD_CLIENT_ID']
    client_secret = current_app.config['DISCORD_CLIENT_SECRET']

    payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
        'code_verifier': code_verifier
    }

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    token_response = requests.post(url=token_url, data=payload, headers=headers)

    if not token_response.ok:
        error_message = token_response.json().get('error_description', 'No description provided.')
        logging.error(f"[AUTH_ERROR] Discord token exchange failed. Status: {token_response.status_code}. Error: {error_message}")
        return jsonify({"error": "Failed to fetch token from Discord"}), 502

    token_data = token_response.json()
    access_token = token_data.get('access_token')

    user_info_url = f"{current_app.config['DISCORD_API_BASE_URL']}/users/@me"
    auth_header = {'Authorization': f'Bearer {access_token}'}
    user_info_response = requests.get(user_info_url, headers=auth_header)

    if not user_info_response.ok:
        return jsonify({"error": "Failed to fetch user info from Discord"}), 502

    user_info = user_info_response.json()
    discord_id = user_info['id']
    discord_username = user_info['username']
    discord_avatar_hash = user_info.get('avatar')

    session = Session()
    user_id_for_jwt = None
    guest_user_to_upgrade = None
    auth_header = request.headers.get('Authorization')
    
    if auth_header:
        try:
            guest_token = auth_header.split(" ")[1]
            secret = current_app.config['SECRET_KEY']
            guest_data = jwt.decode(guest_token, secret, algorithms=['HS256'])
            
            guest_user = session.query(User).filter_by(id=guest_data['user_id']).first()
            if guest_user and guest_user.is_guest:
                guest_user_to_upgrade = guest_user
                logging.info(f"[AUTH] Guest user {guest_user.id} is attempting to link with Discord.")
                
        except Exception as e:
            logging.warning(f"[AUTH_WARN] Invalid guest token provided during callback: {e}")

    try:
        existing_discord_user = session.query(User).filter_by(discord_id=discord_id).with_for_update().first()

        if guest_user_to_upgrade:
            
            if existing_discord_user and existing_discord_user.id != guest_user_to_upgrade.id:
                logging.warning(f"[AUTH_CONFLICT] Guest {guest_user_to_upgrade.id} tried to link to existing Discord user {existing_discord_user.id}.")
                return jsonify({
                    'error': 'account_conflict', 
                    'message': 'This Discord account is already linked to another user. Please log out first.'
                }), 409 
            else:
                guest_user_to_upgrade.discord_id = discord_id
                guest_user_to_upgrade.discord_username = discord_username
                guest_user_to_upgrade.discord_avatar_hash = discord_avatar_hash
                guest_user_to_upgrade.is_guest = False
                
                session.add(guest_user_to_upgrade)
                user_id_for_jwt = guest_user_to_upgrade.id
                logging.info(f"[AUTH] Guest user {guest_user_to_upgrade.id} successfully upgraded to Discord user {discord_id}.")

        else:
            
            if existing_discord_user:
                existing_discord_user.discord_username = discord_username
                existing_discord_user.discord_avatar_hash = discord_avatar_hash
                session.add(existing_discord_user)
                user_id_for_jwt = existing_discord_user.id
                logging.info(f"[AUTH] Existing user logged in: {discord_username} ({discord_id})")
            else:
                new_user = User(
                    discord_id=discord_id, 
                    discord_username=discord_username, 
                    discord_avatar_hash=discord_avatar_hash,
                    is_guest=False
                )
                session.add(new_user)
                session.flush() 
                user_id_for_jwt = new_user.id
                logging.info(f"[AUTH] New user created: {discord_username} ({discord_id})")

        session.commit()
    
    except Exception as e:
        session.rollback()
        logging.error(f"[AUTH_ERROR] Database error during user upsert/merge: {e}", exc_info=True)
        return jsonify({"error": "Could not process user data."}), 500
    finally:
        Session.remove()

    jwt_id = str(uuid.uuid4())
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(days=30) 

    payload = {
        'user_id': user_id_for_jwt,
        'iat': issued_at,
        'exp': expires_at,
        'jti': jwt_id,
        'type': 'access'
    }
    secret = current_app.config['SECRET_KEY']
    app_token = jwt.encode(payload, secret, algorithm='HS256')

    return jsonify({
        'message': 'Login successful!',
        'token': app_token,
        'is_unlimited_pin': False
    })