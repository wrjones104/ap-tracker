import time
import threading
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, current_app
from sqlalchemy import func

from .models import User, TrackedRoom, UserTrackedSlot, NotifiedItem, NotifiedHint
from . import Session

bp = Blueprint('public', __name__, url_prefix='/api/public')

# ==============================================================================
# IN-MEMORY CACHE
# ==============================================================================
stats_cache = {
    'data': None,
    'expires': 0
}
_stats_lock = threading.Lock()

CACHE_DURATION = 900  # 15 Minutes

@bp.route('/stats', methods=['GET'])
def get_public_stats():
    global stats_cache
    current_time = time.time()

    # Serve from cache if valid (no lock needed for read)
    if stats_cache['data'] and current_time < stats_cache['expires']:
        return jsonify(stats_cache['data'])

    # Acquire lock to prevent multiple threads from recalculating at once
    with _stats_lock:
        # Double-check if another thread updated the cache while we were waiting
        if stats_cache['data'] and current_time < stats_cache['expires']:
            return jsonify(stats_cache['data'])

        # Calculate fresh stats
        session = Session()
        try:
            user_count = session.query(func.count(User.id)).scalar()
            room_count = session.query(func.count(TrackedRoom.id)).scalar()
            slot_count = session.query(func.count(UserTrackedSlot.id)).scalar()
            
            item_count = session.query(func.count(NotifiedItem.id)).scalar() or 0
            hint_count = session.query(func.count(NotifiedHint.id)).scalar() or 0
            total_notifications = item_count + hint_count

            yesterday = datetime.utcnow() - timedelta(hours=24)
            active_games_count = session.query(func.count(TrackedRoom.id))\
                .filter(TrackedRoom.last_successful_poll >= yesterday).scalar()

            data = {
                "total_users": user_count,
                "total_rooms": room_count,
                "total_slots": slot_count,
                "active_games_24h": active_games_count,
                "total_notifications": total_notifications
            }

            # Update cache
            stats_cache['data'] = data
            stats_cache['expires'] = current_time + CACHE_DURATION
            
            if current_app.logger:
                current_app.logger.info(f"[STATS] Refreshed public stats: {data}")

            return jsonify(data)

        except Exception as e:
            if current_app.logger:
                current_app.logger.error(f"[STATS] Error calculating stats: {e}")
            return jsonify({"error": "Stats temporarily unavailable"}), 500