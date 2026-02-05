import logging
import aiohttp
import os
import re
from urllib.parse import urlparse
from app import Session
from app.models import TrackedRoom

CHEESE_USER_AGENT_BASE = 'ArchipelagoAlerts'
CHEESE_CONTACT = 'github.com/wrjones104'

def get_app_version():
    """Extracts version from the Android build.gradle.kts file."""
    try:
        gradle_path = os.path.join(os.path.dirname(__file__), '../../android/app/build.gradle.kts')
        if os.path.exists(gradle_path):
            with open(gradle_path, 'r') as f:
                content = f.read()
                match = re.search(r'versionName\s*=\s*"([^"]+)"', content)
                if match:
                    return match.group(1)
    except Exception as e:
        logging.warning(f"[VERSION] Could not read version from gradle: {e}")
    
    return "1.0.0" # Fallback

def get_user_agent_string():
    """Returns the raw User-Agent string for use in any HTTP client."""
    version = get_app_version()
    return f'{CHEESE_USER_AGENT_BASE}/{version} (contact: {CHEESE_CONTACT})'

def get_cheese_headers():
    """Returns the full headers dict for Cheese Tracker."""
    return {
        'User-Agent': get_user_agent_string(),
        'Content-Type': 'application/json'
    }

def extract_ap_room_id(url_string):
    if not url_string: return None
    try:
        parsed = urlparse(url_string)
        parts = parsed.path.strip('/').split('/')
        if len(parts) >= 2 and parts[0] == 'room':
            return parts[1]
    except Exception:
        pass
    return None

async def fetch_json_with_status(url, session=None, headers=None, timeout=15):
    """
    Fetches JSON and returns a tuple: (json_data, status_code).
    Used when the status code (e.g. 404) matters for logic.
    """
    should_close_session = False
    if not session:
        session = aiohttp.ClientSession()
        should_close_session = True
        
    json_data = None
    status_code = 0
    
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
            status_code = response.status
            if status_code == 200:
                try:
                    json_data = await response.json()
                except Exception:
                    # Logic: 200 OK but bad JSON is treated as "No Data" but valid connection
                    pass
    except Exception as e:
        # Network errors usually result in status_code=0
        pass
    finally:
        if should_close_session:
            await session.close()
            
    return json_data, status_code

def db_suspend_room(db_id, reason="Unknown"):
    """
    Suspends a room in the database to stop polling.
    """
    session = Session()
    try:
        room = session.query(TrackedRoom).filter_by(id=db_id).first()
        if room and not room.is_suspended:
            room.is_suspended = True
            room.failed_poll_count = 0 
            logging.info(f"[SUSPEND] Room {db_id} suspended. Reason: {reason}")
            session.commit()
            return True
        return False
    except Exception as e:
        logging.error(f"[DB_ERROR] Failed to suspend room {db_id}: {e}")
        session.rollback()
        return False
    finally:
        Session.remove()