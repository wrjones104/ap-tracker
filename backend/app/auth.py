import jwt
import requests
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

    if not code:
        return jsonify({'error': 'Missing authorization code'}), 400

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
        print(f"[AUTH_ERROR] Discord responded with: {token_response.json()}")
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
    user = session.query(User).filter_by(discord_id=discord_id).first()
    if not user:
        user = User(discord_id=discord_id, discord_username=discord_username, discord_avatar_hash=discord_avatar_hash)
        session.add(user)
        session.commit()
        print(f"[AUTH] New user created: {discord_username} ({discord_id})")
    else:
        user.discord_username = discord_username
        user.discord_avatar_hash = discord_avatar_hash
        session.commit()
        print(f"[AUTH] Existing user logged in: {discord_username} ({discord_id})")

    payload = {
        'user_id': user.id,
        'exp': datetime.now(timezone.utc) + timedelta(days=30)
    }
    secret = current_app.config['SECRET_KEY']
    app_token = jwt.encode(payload, secret, algorithm='HS256')

    return jsonify({
        'message': 'Login successful!',
        'token': app_token
    })