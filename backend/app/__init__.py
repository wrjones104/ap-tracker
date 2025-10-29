import os
import json
import requests
import firebase_admin
import psutil
import logging  # <-- NEW
import sys      # <-- NEW

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

# Get the environment, default to 'production' if not set
FLASK_ENV = os.getenv('FLASK_ENV', 'production')

# Map environment names to logging levels
log_levels = {
    'development': logging.DEBUG,
    'uat': logging.INFO,
    'production': logging.INFO,  # Default production to INFO
}
log_level = log_levels.get(FLASK_ENV, logging.INFO)

# Configure the root logger
logging.basicConfig(
    level=log_level,
    # Format includes timestamp, level, function name (for context), and message
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s',
    # Stream to stdout so it can be captured by Cloud Log, Docker, etc.
    stream=sys.stdout
)

logging.info(f"Logging level set to {logging.getLevelName(log_level)} for '{FLASK_ENV}' environment.")

# ==============================================================================
# 1. CONFIGURATION & CONSTANTS
# ==============================================================================

DATABASE_FILE = "ap_tracker.db"
POLLING_INTERVAL_SECONDS = 180
SUPERVISOR_INTERVAL_SECONDS = 60
FIREBASE_KEY_FILE = "service-account-key.json"

process = psutil.Process(os.getpid())
process.cpu_percent(interval=None)

# ==============================================================================
# 2. DATABASE SETUP
# ==============================================================================

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

engine = create_engine(
    f"sqlite:///{DATABASE_FILE}",
    connect_args={"check_same_thread": False, "timeout": 30}
)
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

_firebase_app = None
def get_firebase_app():
    global _firebase_app
    if _firebase_app is None:
        try:
            cred = credentials.Certificate(FIREBASE_KEY_FILE)
            _firebase_app = firebase_admin.initialize_app(cred, {'http_client': firebase_http_session})
            logging.info("[FIREBASE] Firebase initialized successfully.") # <-- MODIFIED
        except Exception as e:
            logging.critical(f"[FIREBASE] !!! FIREBASE ERROR: Could not initialize. Error: {e}") # <-- MODIFIED
    return _firebase_app

# ==============================================================================
# 4. APPLICATION FACTORY
# ==============================================================================

def create_app():
    """Creates and configures an instance of the Flask application."""
    app = Flask(__name__)
    app.config.from_object(app_config)
    
    # Use logging, not print
    log_mode = 'DEBUG' if app.config.get('DEBUG') else 'PRODUCTION'
    logging.info(f"[MAIN] Application running in {log_mode} mode (FLASK_ENV: {FLASK_ENV}).")
    
    from . import models
    models.Base.metadata.create_all(engine)
    logging.info("[MAIN] Database tables verified/created.") # <-- MODIFIED

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        Session.remove()

    from . import api
    app.register_blueprint(api.bp)

    from . import auth
    app.register_blueprint(auth.bp)

    return app