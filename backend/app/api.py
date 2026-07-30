import logging
from flask import Blueprint

from app.routes.common import (
    token_required,
    handle_db_errors,
    log_api_call,
    format_iso_z,
    chunked_iterable
)
from app.routes.auth_routes import auth_bp
from app.routes.user_routes import user_bp
from app.routes.rooms_routes import rooms_bp
from app.routes.slots_routes import slots_bp
from app.routes.thresholds_routes import thresholds_bp
from app.routes.history_routes import history_bp
from app.routes.game_routes import game_bp
from app.routes.whats_new_routes import whats_new_bp

bp = Blueprint('api', __name__)

# Re-export decorators for backward compatibility with external imports (e.g. api_cheese)
__all__ = [
    'bp',
    'token_required',
    'handle_db_errors',
    'log_api_call',
    'format_iso_z',
    'chunked_iterable'
]

def register_api_routes(app):
    """Registers all domain-driven route blueprints with the Flask application."""
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(rooms_bp)
    app.register_blueprint(slots_bp)
    app.register_blueprint(thresholds_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(game_bp)
    app.register_blueprint(whats_new_bp)
    logging.info("[API] All modular route blueprints registered successfully.")

