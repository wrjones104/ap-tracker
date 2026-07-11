import os
import json
import psutil
import logging
import sys
import base64

from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session
from dotenv import load_dotenv
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from config import app_config

load_dotenv()

# ==============================================================================
# 0. LOGGING SETUP (NEW)
# ==============================================================================

FLASK_ENV = os.getenv('FLASK_ENV', 'production')

log_levels = {
    'development': logging.DEBUG,
    'uat': logging.INFO,
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
VAPID_PRIVATE_KEY_FILE = "vapid/private_key.pem"
VAPID_PUBLIC_KEY_FILE = "vapid/public_key.pem"
VAPID_PUBLIC_KEY = ""
VAPID_CLAIMS_FILE = "vapid/claims.json"
VAPID_CLAIMS = "{}"

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

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args
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
# 3. GLOBAL SERVICES (VAPID Keys and Claims)
# ==============================================================================

if (Path(VAPID_PUBLIC_KEY_FILE).exists()):
  with open(VAPID_PUBLIC_KEY_FILE, "rb") as f:
      public_key = serialization.load_pem_public_key(f.read())
  raw = public_key.public_bytes(
      encoding=serialization.Encoding.X962,
      format=serialization.PublicFormat.UncompressedPoint,
  )
  VAPID_PUBLIC_KEY = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

if (Path(VAPID_CLAIMS_FILE).exists()):
  with open(VAPID_CLAIMS_FILE, "rb") as f:
      claims = json.load(f)
  VAPID_CLAIMS = claims

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
        # This lets you just delete the .db file and restart.
        models.Base.metadata.create_all(engine)
        logging.info("[MAIN] SQLite DB detected. Tables verified/created.")
    else:
        # For prod (Postgres), we trust Alembic to handle the schema.
        logging.info("[MAIN] Production database engine initialized.")

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        Session.remove()

    from . import api
    app.register_blueprint(api.bp)

    from . import auth
    app.register_blueprint(auth.bp)

    from . import api_public
    app.register_blueprint(api_public.bp)

    from . import main
    app.register_blueprint(main.bp)

    from .api_cheese import bp as cheese_bp
    app.register_blueprint(cheese_bp, url_prefix='/integrations/cheese')

    return app
