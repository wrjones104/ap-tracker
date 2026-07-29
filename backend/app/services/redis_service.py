import os
import logging
import json

try:
    import redis
except ImportError:
    redis = None

_redis_client = None

def get_redis_client():
    """
    Returns a connected Redis client instance.
    Falls back to None if Redis is unavailable or unconfigured.
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    if not redis:
        logging.warning("[REDIS] Python 'redis' library not installed. Redis caching disabled.")
        return None

    try:
        client = redis.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3)
        client.ping()
        _redis_client = client
        logging.info(f"[REDIS] Successfully connected to Redis at {redis_url} (RESP3)")
        return _redis_client
    except Exception as e:
        if 'HELLO' in str(e) or 'unknown command' in str(e).lower():
            try:
                logging.info(f"[REDIS] Older Redis server detected on {redis_url}. Retrying with protocol=2 (RESP2)...")
                client = redis.from_url(redis_url, protocol=2, socket_timeout=3, socket_connect_timeout=3)
                client.ping()
                _redis_client = client
                logging.info(f"[REDIS] Successfully connected to Redis at {redis_url} (RESP2 legacy mode)")
                return _redis_client
            except Exception as e2:
                logging.warning(f"[REDIS] Could not connect to Redis at {redis_url} with protocol=2: {e2}. Falling back to in-memory mode.")
                return None
        logging.warning(f"[REDIS] Could not connect to Redis at {redis_url}: {e}. Falling back to in-memory mode.")
        return None

def publish_event(channel: str, data: dict) -> bool:
    """
    Publishes a JSON payload to a Redis Pub/Sub channel.
    """
    client = get_redis_client()
    if not client:
        return False
    try:
        payload = json.dumps(data)
        client.publish(channel, payload)
        return True
    except Exception as e:
        logging.error(f"[REDIS_ERROR] Failed to publish event to {channel}: {e}", exc_info=True)
        return False

def cache_get(key: str) -> str | None:
    """Gets a string value from Redis cache."""
    client = get_redis_client()
    if not client:
        return None
    try:
        val = client.get(key)
        return val.decode('utf-8') if isinstance(val, bytes) else val
    except Exception as e:
        logging.warning(f"[REDIS_WARN] Cache get failed for {key}: {e}")
        return None

def cache_set(key: str, value: str, ttl_seconds: int = 86400) -> bool:
    """Sets a string value in Redis cache with TTL (default 24h)."""
    client = get_redis_client()
    if not client:
        return False
    try:
        client.setex(key, ttl_seconds, value)
        return True
    except Exception as e:
        logging.warning(f"[REDIS_WARN] Cache set failed for {key}: {e}")
        return False
