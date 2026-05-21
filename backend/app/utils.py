import logging
import aiohttp
import os
import re
from urllib.parse import urlparse
from datetime import timezone
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

from ipaddress import ip_address
import json

def _validate_ip(ip):
    """Checks if an IP address is safe to connect to."""
    if os.environ.get('FLASK_ENV', 'production') == 'development' and (ip.is_loopback or ip.is_private):
        return

    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or not ip.is_global:
        raise ValueError(f"Blocked request to forbidden IP: {ip}")
    if str(ip) == "169.254.169.254":
        raise ValueError("Blocked request to Cloud Metadata IP")

class SSRFProtectedResolver(aiohttp.DefaultResolver):
    async def resolve(self, host: str, port: int, family: int) -> list[dict]:
        addresses = await super().resolve(host, port, family)
        for addr in addresses:
            ip = ip_address(addr['host'])
            _validate_ip(ip)
        return addresses

class SSRFProtectedTCPConnector(aiohttp.TCPConnector):
    def __init__(self, *args, **kwargs):
        kwargs['resolver'] = SSRFProtectedResolver()
        super().__init__(*args, **kwargs)

    async def connect(self, req, traces, timeout):
        try:
            ip = ip_address(req.host)
            _validate_ip(ip)
        except ValueError as e:
            if "Blocked request" in str(e):
                raise
            pass

        return await super().connect(req, traces, timeout)


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

def get_web_base_url(hostname: str) -> str:
    """
    Returns the full web base URL (scheme + host [+ port]) for the given hostname.
    In development, if the hostname is a loopback/private address or contains a local host/port,
    it defaults to http:// instead of https://.
    """
    if not hostname:
        return "https://archipelago.gg"
        
    use_http = False
    if os.environ.get('FLASK_ENV', 'production') == 'development':
        host_only = hostname.split(':')[0]
        if host_only in ('localhost', '127.0.0.1', '10.0.2.2'):
            use_http = True
        else:
            import socket
            try:
                resolved_ip = socket.gethostbyname(host_only)
                from ipaddress import ip_address
                ip = ip_address(resolved_ip)
                if ip.is_private or ip.is_loopback:
                    use_http = True
            except Exception:
                pass

            if not use_http:
                if '.' not in host_only:
                    use_http = True
                elif host_only.endswith(('.local', '.lan', '.internal', '.test', '.example')):
                    use_http = True
                
    scheme = "http" if use_http else "https"
    return f"{scheme}://{hostname}"

async def verify_ap_server(hostname: str, room_id: str):
    """
    Verifies that the given Archipelago server URL is valid and reachable.
    It checks the status endpoint and performs a websocket handshake to verify it's an AP server.
    Raises ValueError with a user-friendly message if any step fails.
    """
    if not hostname or not room_id:
        raise ValueError("Hostname and room_id are required.")

    connector = SSRFProtectedTCPConnector()
    async with aiohttp.ClientSession(connector=connector) as session:
        # Step 1: Check room status endpoint
        base_url = get_web_base_url(hostname)
        status_url = f"{base_url}/api/room_status/{room_id}"

        try:
            # We enforce a strict timeout of 30 seconds, and payload size limit by reading raw bytes
            async with session.get(status_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 404:
                    raise ValueError(f"Room {room_id} not found on server {hostname}.")
                response.raise_for_status()

                # Limit read to 20MB to prevent DoS via memory exhaustion
                raw_data = bytearray()
                limit = 20 * 1024 * 1024
                while len(raw_data) < limit:
                    chunk = await response.content.read(65536)
                    if not chunk:
                        break
                    raw_data.extend(chunk)
                else:
                    raise ValueError("Server response is too large.")

                status_data = json.loads(raw_data)

                if not isinstance(status_data, dict):
                    raise ValueError("Unexpected response format from room status API.")

                port = status_data.get('last_port', '')
                ap_tracker_id = status_data.get('tracker')

                if not port:
                    raise ValueError("Could not find server port from room status.")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Could not connect to the room to verify its status: {e}")

        # Step 2: Attempt WebSocket handshake
        clean_host = hostname.split(':')[0]
        uris_to_try = [
            f"wss://{clean_host}:{port}",
            f"ws://{clean_host}:{port}"
        ]

        parts = clean_host.split('.')
        base_domain = None
        if len(parts) > 2:
            base_domain = ".".join(parts[1:])
            uris_to_try.extend([
                f"wss://{base_domain}:{port}",
                f"ws://{base_domain}:{port}"
            ])

        ws_success = False
        successful_hostname = clean_host

        for uri in uris_to_try:
            if ws_success:
                break

            try:
                # 10-second timeout for websocket connection and read
                async with session.ws_connect(uri, timeout=10) as ws:
                    msg = await ws.receive(timeout=10)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        room_info_msg = json.loads(msg.data)
                        if isinstance(room_info_msg, list) and len(room_info_msg) > 0:
                            if room_info_msg[0].get('cmd') == 'RoomInfo':
                                ws_success = True
                                # Keep track of which hostname succeeded
                                if uri.startswith(f"wss://{base_domain}") or uri.startswith(f"ws://{base_domain}"):
                                    successful_hostname = base_domain
                                break
            except Exception as e:
                pass

        if not ws_success:
            raise ValueError("Failed to perform Archipelago server handshake. Ensure the server is running and accessible.")

        # Return relevant data to be used by the caller
        players_raw = status_data.get('players', [])
        player_list = [{'slot_id': i + 1, 'name': p[0], 'game': p[1]} for i, p in enumerate(players_raw)]
        total_slots = len(player_list)
        players_json = json.dumps(player_list)

        # Extract the correct address format
        final_address = f"{successful_hostname}:{port}"

        return {
            'hostname': hostname, # Keep hostname (which may include port in local dev) intact for references
            'room_id': room_id,
            'ap_tracker_id': ap_tracker_id,
            'cached_full_address': final_address,
            'cached_players_json': players_json,
            'cached_total_slots': total_slots
        }


async def fetch_json_with_status(url, session=None, headers=None, timeout=60):
    """
    Fetches JSON and returns a tuple: (json_data, status_code).
    Used when the status code (e.g. 404) matters for logic.
    """
    should_close_session = False
    if not session:
        session = aiohttp.ClientSession(connector=SSRFProtectedTCPConnector())
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
        
def is_snoozed(user_prefs, slot_prefs, now_utc, user_id, slot_id, context_label="item"):
    """
    Checks if a notification should be suppressed due to Global or Slot snooze.
    Handles timezone normalization (naive -> UTC aware).
    """
    # 1. Check Global Snooze
    global_snooze = user_prefs.global_snooze_until
    if global_snooze:
        # If DB returned naive time, force it to be UTC aware
        if global_snooze.tzinfo is None:
            global_snooze = global_snooze.replace(tzinfo=timezone.utc)
        
        if global_snooze > now_utc:
            logging.debug(f"[NOTIFY_SNOOZE] User {user_id} is globally snoozed. Suppressing {context_label}.")
            return True

    # 2. Check Slot Snooze
    if slot_prefs:
        slot_snooze = slot_prefs.snooze_until
        if slot_snooze:
            # If DB returned naive time, force it to be UTC aware
            if slot_snooze.tzinfo is None:
                slot_snooze = slot_snooze.replace(tzinfo=timezone.utc)

            if slot_snooze > now_utc:
                logging.debug(f"[NOTIFY_SNOOZE] User {user_id} has snoozed Slot {slot_id} ({context_label}).")
                return True
                
    return False

