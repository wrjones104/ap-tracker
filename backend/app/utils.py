import logging
import os
import re
from urllib.parse import urlparse

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