import os
import json
import requests
import firebase_admin
import psutil

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
# 1. CONFIGURATION & CONSTANTS
# ==============================================================================

DATABASE_FILE = "ap_tracker.db"
POLLING_INTERVAL_SECONDS = 60
SUPERVISOR_INTERVAL_SECONDS = 30
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
            print("[FIREBASE] Firebase initialized successfully.")
        except Exception as e:
            print(f"[FIREBASE] !!! FIREBASE ERROR: Could not initialize. Error: {e}")
    return _firebase_app

# ==============================================================================
# 4. APPLICATION FACTORY
# ==============================================================================

def create_app():
    """Creates and configures an instance of the Flask application."""
    app = Flask(__name__)
    app.config.from_object(app_config)
    print(f"[MAIN] Application running in {'DEBUG' if app.config.get('DEBUG') else 'PRODUCTION'} mode.")
    
    from . import models
    models.Base.metadata.create_all(engine)
    print("[MAIN] Database tables verified/created.")

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        Session.remove()

    from . import api
    app.register_blueprint(api.bp)

    from . import auth
    app.register_blueprint(auth.bp)

    return app