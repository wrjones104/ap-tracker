import jwt
import requests
import logging
import uuid
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, current_app, url_for
# from oauthlib.oauth2 import WebApplicationClient

from .models import User
from . import Session

bp = Blueprint('auth', __name__, url_prefix='/auth')

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
    try:
        user = session.query(User).filter_by(discord_id=discord_id).with_for_update().first()

        if not user:
            user = User(discord_id=discord_id, discord_username=discord_username, discord_avatar_hash=discord_avatar_hash)
            session.add(user)
            logging.info(f"[AUTH] New user created: {discord_username} ({discord_id})")
        else:
            user.discord_username = discord_username
            user.discord_avatar_hash = discord_avatar_hash
            logging.info(f"[AUTH] Existing user logged in: {discord_username} ({discord_id})")

        session.commit()
    except Exception as e:
        session.rollback()
        logging.error(f"[AUTH_ERROR] Database error during user upsert: {e}", exc_info=True)
        return jsonify({"error": "Could not process user data."}), 500
    finally:
        Session.remove()

    # (V2) We now add the jti claim for better token tracking / blocklisting
    # And the 'iat' claim to know when it was issued
    jwt_id = str(uuid.uuid4())
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(days=30)

    payload = {
        'user_id': user.id,
        'iat': issued_at,
        'exp': expires_at,
        'jti': jwt_id,
        'type': 'access' # V3: Differentiate from refresh tokens
    }
    secret = current_app.config['SECRET_KEY']
    app_token = jwt.encode(payload, secret, algorithm='HS256')

    return jsonify({
        'message': 'Login successful!',
        'token': app_token,
        'is_unlimited_pin': False
    })