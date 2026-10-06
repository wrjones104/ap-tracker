import logging
import os
import jwt
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.exc import IntegrityError

from app import Session
from app.models import JWTBlocklist
from app.routes.common import log_api_call, token_required, handle_db_errors

auth_bp = Blueprint('auth_routes', __name__)

# The oldest app versionCode the server still supports. The app checks it on
# launch and shows the update screen below it. Set MIN_APP_VERSION in
# backend/.env and restart -- no release needed -- before deploying a server
# change that withdraws something older apps rely on. See #343.
DEFAULT_MIN_APP_VERSION = 9


def min_app_version():
    raw = os.getenv('MIN_APP_VERSION', '').strip()
    if not raw:
        return DEFAULT_MIN_APP_VERSION
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        # A typo. Failing /config would silently drop the floor, because the
        # app fails open when it cannot read it, so keep the default instead.
        logging.error(
            f"[CONFIG_ERROR] MIN_APP_VERSION={raw!r} is not a positive versionCode; "
            f"using {DEFAULT_MIN_APP_VERSION}."
        )
        return DEFAULT_MIN_APP_VERSION
    return value

@auth_bp.route('/logout', methods=['POST'])
@handle_db_errors
@log_api_call
@token_required
def logout(current_user):
    """
    Logs the user out by adding their token's JTI to the blocklist.
    """
    token = request.headers['Authorization'].split(" ")[1]
    secret = current_app.config['SECRET_KEY']

    try:
        data = jwt.decode(token, secret, algorithms=['HS256'], options={"verify_exp": False})
    except jwt.InvalidTokenError:
        return jsonify({'error': 'Invalid token'}), 401

    jti = data.get('jti')
    exp = data.get('exp')

    if not jti or not exp:
        return jsonify({'error': 'Token is missing JTI or EXP claim'}), 400

    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)

    session = Session()
    try:
        session.add(JWTBlocklist(jti=jti, expires_at=expires_at))
        session.commit()
    except IntegrityError:
        session.rollback()
        logging.info(f"JTI {jti} for user {current_user.id} was already blocklisted.")
    except Exception as e:
        session.rollback()
        logging.error(f"Failed to add JTI to blocklist for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'error': 'Logout failed.'}), 500
    finally:
        Session.remove()

    logging.info(f"User {current_user.id} logged out successfully.")
    return jsonify({'message': 'Successfully logged out.'}), 200

@auth_bp.route('/config', methods=['GET'])
@log_api_call 
def get_public_config():
    """
    Returns public configuration data (e.g., minimum required app version).
    """
    try:
        return jsonify({'min_app_version': min_app_version()})
    except Exception as e:
        logging.error(f"[CONFIG_ERROR] Failed to serve /config: {e}", exc_info=True)
        return jsonify({'error': 'Could not fetch server config.'}), 500
