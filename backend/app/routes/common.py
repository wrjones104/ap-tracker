import logging
import json
import jwt
import itertools
from datetime import datetime, timezone
from functools import wraps
from flask import request, jsonify, current_app
from sqlalchemy.exc import OperationalError, IntegrityError

from app import Session
from app.models import User, JWTBlocklist

def chunked_iterable(iterable, size):
    """Yields successive chunks from an iterable."""
    it = iter(iterable)
    while True:
        chunk = tuple(itertools.islice(it, size))
        if not chunk:
            break
        yield chunk

def format_iso_z(dt_obj):
    """Formats a datetime object to ISO-8601 with strictly 'Z' for UTC."""
    if not dt_obj:
        return None
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    return dt_obj.isoformat().replace("+00:00", "Z")

def log_api_call(f):
    """A decorator to log API request and response."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        payload = ""
        if request.is_json and request.content_length:
            try:
                payload = json.dumps(request.json)
            except Exception:
                payload = "Error dumping JSON payload"
        
        logging.debug(f"[API] Call: {request.method} {request.path} | Payload: {payload}")
        
        try:
            response = f(*args, **kwargs)
            
            response_data = ""
            if hasattr(response, 'get_data'):
                try:
                    response_data = response.get_data(as_text=True)[:500] 
                except Exception:
                    response_data = "Error getting response data"
            else:
                response_data = str(response)

            logging.debug(f"[API] Response: {request.path} | Body: {response_data}...")
            return response
        
        except Exception as e:
            logging.error(f"[API] Error: {request.path} | Exception: {e}", exc_info=True)
            raise e
            
    return decorated_function

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                logging.warning(f"Malformed Authorization header for {request.method} {request.path}.")
                return jsonify({'error': 'Malformed Authorization header'}), 401

        if not token:
            logging.info(f"Missing auth token for {request.method} {request.path}.")
            return jsonify({'error': 'Authentication token is missing'}), 401

        session = None
        try:
            secret = current_app.config['SECRET_KEY']
            data = jwt.decode(token, secret, algorithms=['HS256'])

            jti = data.get('jti')
            if not jti:
                logging.warning(f"Auth failure: Token is missing 'jti' claim.")
                return jsonify({'error': 'Invalid token format'}), 401

            session = Session()

            is_blocked = session.query(JWTBlocklist).filter_by(jti=jti).first()
            if is_blocked:
                logging.warning(f"Auth failure: Blocked token used by user {data.get('user_id')}.")
                return jsonify({'error': 'Token has been revoked'}), 401

            current_user = session.query(User).filter_by(id=data['user_id']).first()
            if not current_user:
                logging.warning(f"Auth success, but user {data['user_id']} not found in DB.")
                return jsonify({'error': 'User not found'}), 401
            
            current_user.last_activity = datetime.utcnow()
            session.commit() 
            
            session.refresh(current_user)
            session.expunge(current_user)

        except jwt.ExpiredSignatureError:
            logging.info(f"Auth failure: Token has expired.")
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            logging.warning(f"Auth failure: Invalid token received.")
            return jsonify({'error': 'Invalid token'}), 401
        
        except Exception as e:
            if session:
                session.rollback()
            logging.error(f"Token processing error: {e}", exc_info=True)
            return jsonify({'error': 'An internal server error occurred.'}), 500
        finally:
            if session:
                Session.remove()
                
        return f(current_user, *args, **kwargs)
    return decorated_function

def handle_db_errors(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session = Session()
        try:
            result = f(*args, **kwargs)
            session.commit()
            return result
        except OperationalError as e:
            session.rollback()
            logging.error(f"[API_ERROR] Database locked or operational error: {e}")
            return jsonify({'error': 'Database is busy, please try again.'}), 503
        except IntegrityError as e:
            session.rollback()
            logging.warning(f"[API_ERROR] Database integrity error: {e}")
            return jsonify({'error': 'A record with this value already exists.'}), 409
        except Exception as e:
            session.rollback()
            logging.error(f"[API_ERROR] An unhandled API error occurred: {e}", exc_info=True)
            return jsonify({'error': 'An internal server error occurred.'}), 500
        finally:
            Session.remove()
    return decorated_function
