import os
import json
import requests
import firebase_admin
import psutil
import logging
import sys    

from flask import Flask
from waitress import serve
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.engine import Engine
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from firebase_admin import credentials, messaging
from config import app_config

load_dotenv()

# ==============================================================================
# 0. LOGGING SETUP (NEW)
# ==============================================================================

FLASK_ENV = os.getenv('FLASK_ENV', 'production')
LOG_LEVEL_ENV = os.getenv('LOG_LEVEL', '').upper()

if LOG_LEVEL_ENV and hasattr(logging, LOG_LEVEL_ENV):
    log_level = getattr(logging, LOG_LEVEL_ENV)
else:
    log_levels = {
        'development': logging.DEBUG,
        'uat': logging.DEBUG,
        'production': logging.INFO, 
    }
    log_level = log_levels.get(FLASK_ENV, logging.INFO)

logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s',
    stream=sys.stdout
)

logging.info(f"Logging level set to {logging.getLevelName(log_level)} for '{FLASK_ENV}' environment.")

# ==============================================================================
# 1. CONFIGURATION & CONSTANTS
# ==============================================================================

DATABASE_URL = os.environ.get('DATABASE_URL', "sqlite:///./ap_tracker.db")
POLLING_INTERVAL_SECONDS = 300
SUPERVISOR_INTERVAL_SECONDS = 60
FIREBASE_KEY_FILE = "service-account-key.json"

process = psutil.Process(os.getpid())
process.cpu_percent(interval=None)

# ==============================================================================
# 2. DATABASE SETUP
# ==============================================================================

is_sqlite = DATABASE_URL.startswith("sqlite")
connect_args = {}

if is_sqlite:
    connect_args = {"check_same_thread": False, "timeout": 30}
else:
    connect_args = {"connect_timeout": 10}

pool_kwargs = {}
if not is_sqlite:
    pool_kwargs = {
        'pool_size': 10,         # Base persistent connections
        'max_overflow': 5,       # Burst capacity above pool_size
        'pool_timeout': 30,      # Seconds to wait for a connection
        'pool_recycle': 1800,    # Recycle connections every 30 min
        'pool_pre_ping': True,   # Verify connections are alive before use
    }

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    **pool_kwargs
)

if is_sqlite:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma_instance(dbapi_connection, connection_record):
        """Issues PRAGMA for WAL mode on connection for SQLite."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
    
    logging.info("SQLite database detected. WAL mode enabled.")

session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)

# ==============================================================================
# 3. GLOBAL SERVICES (Firebase, HTTP Session)
# ==============================================================================

retry_strategy = Retry(
    total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
)
adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retry_strategy)
firebase_http_session = requests.Session()
firebase_http_session.mount("https://", adapter)

# Cache of initialized firebase app instances by platform
import threading
_firebase_apps = {}
_firebase_lock = threading.Lock()

def get_firebase_app(platform='android'):
    global _firebase_apps
    platform = (platform or 'android').lower().strip()
    if platform not in ['android', 'ios']:
        platform = 'android'
        
    if platform not in _firebase_apps:
        with _firebase_lock:
            if platform not in _firebase_apps:
                try:
                    if platform == 'android':
                        key_file = os.environ.get('FIREBASE_KEY_FILE_ANDROID', 'service-account-key.json')
                        if not os.path.exists(key_file):
                            logging.error(f"[FIREBASE] Key file for {platform} not found: {key_file}")
                            return None
                        try:
                            app = firebase_admin.get_app()
                        except ValueError:
                            cred = credentials.Certificate(key_file)
                            app = firebase_admin.initialize_app(cred, {'http_client': firebase_http_session})
                        _firebase_apps[platform] = app
                        logging.info("[FIREBASE] Android Firebase app initialized successfully.")
                    elif platform == 'ios':
                        key_file = os.environ.get('FIREBASE_KEY_FILE_IOS', 'service-account-key-ios.json')
                        if not os.path.exists(key_file):
                            logging.warning(f"[FIREBASE] Key file for {platform} not found: {key_file}. iOS push notifications will be skipped.")
                            return None
                        try:
                            app = firebase_admin.get_app(name='ios')
                        except ValueError:
                            cred = credentials.Certificate(key_file)
                            app = firebase_admin.initialize_app(cred, {'http_client': firebase_http_session}, name='ios')
                        _firebase_apps[platform] = app
                        logging.info("[FIREBASE] iOS Firebase app initialized successfully.")
                except Exception as e:
                    if platform == 'ios':
                        logging.warning(f"[FIREBASE] Could not initialize iOS Firebase app: {e}. iOS push notifications will be skipped.")
                    else:
                        logging.critical(f"[FIREBASE] !!! Android Firebase app error: Could not initialize. Error: {e}")
            
    return _firebase_apps.get(platform)

# ==============================================================================
# 4. APPLICATION FACTORY
# ==============================================================================

def create_app():
    """Creates and configures an instance of the Flask application."""
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-fallback-key-do-not-use-in-prod')
    app.config['DISCORD_CLIENT_ID'] = os.getenv('DISCORD_CLIENT_ID')
    app.config['DISCORD_CLIENT_SECRET'] = os.getenv('DISCORD_CLIENT_SECRET')
    app.config['DISCORD_REDIRECT_URI'] = os.getenv('DISCORD_REDIRECT_URI')
    app.config['ENCRYPTION_KEY'] = os.getenv('ENCRYPTION_KEY')
    allowed_hostnames_str = os.getenv('ALLOWED_HOSTNAMES', '')
    app.config['ALLOWED_HOSTNAMES'] = [h.strip() for h in allowed_hostnames_str.split(',') if h]
    app.config.from_object(app_config)
    
    log_mode = 'DEBUG' if app.config.get('DEBUG') else 'PRODUCTION'
    logging.info(f"[MAIN] Application running in {log_mode} mode (FLASK_ENV: {FLASK_ENV}).")
    
    from . import models

    if is_sqlite:
        # For local dev, auto-create all tables on startup.
        models.Base.metadata.create_all(engine)
        logging.info("[MAIN] SQLite DB detected. Tables verified/created.")
    else:
        # For prod (Postgres), we trust Alembic to handle the schema.
        logging.info("[MAIN] Production database engine initialized.")

    try:
        from .services.threshold_service import reconcile_slot_item_counts
        reconcile_slot_item_counts()
    except Exception as e:
        logging.warning(f"[MAIN] Startup slot item count reconciliation skipped: {e}")


    @app.teardown_appcontext
    def shutdown_session(exception=None):
        Session.remove()

    from . import api
    app.register_blueprint(api.bp)
    api.register_api_routes(app)

    from . import auth
    app.register_blueprint(auth.bp)

    from . import api_public
    app.register_blueprint(api_public.bp)

    from . import main
    app.register_blueprint(main.bp)

    from .api_cheese import bp as cheese_bp
    app.register_blueprint(cheese_bp, url_prefix='/integrations/cheese')

    return app
