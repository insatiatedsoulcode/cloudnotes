"""
Cache-aside layer backed by Redis.

Cache-aside pattern:
  1. On read:  check Redis → hit: return cached data  → miss: query DB, store, return
  2. On write: update DB → invalidate the relevant cache key(s)

All operations catch Redis exceptions and degrade gracefully so the app
continues to work even if Redis is temporarily down — it just gets slower
(every request hits the DB instead of the cache).

TTLs:
  NOTES_LIST_TTL    30 s  — list changes on every write; short TTL limits staleness
  NOTES_DETAIL_TTL 300 s  — individual notes are read far more often than written
"""

import json
from typing import Any, Optional

import redis as redis_lib

from app.config import settings
from app.logger import get_logger

log = get_logger("cache")

NOTES_LIST_TTL = 30       # seconds — cache-aside for GET /notes/
NOTES_DETAIL_TTL = 300    # 5 minutes — cache-aside for GET /notes/{id}

# Module-level singleton. Replaced with fakeredis in tests via override_for_testing().
_redis_client: Optional[redis_lib.Redis] = None


def get_redis() -> redis_lib.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_lib.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1,   # fail fast if Redis is down
            socket_timeout=1,
        )
    return _redis_client


def override_for_testing(client: Optional[redis_lib.Redis]) -> None:
    """Swap the Redis client — called by the test fixture to inject fakeredis."""
    global _redis_client
    _redis_client = client


def cache_get(key: str) -> Optional[Any]:
    """Return deserialized value from cache, or None on miss or error."""
    try:
        raw = get_redis().get(key)
        if raw is None:
            log.debug("CACHE MISS  key=%s", key)
            return None
        log.debug("CACHE HIT   key=%s", key)
        return json.loads(raw)
    except Exception as exc:
        log.warning("CACHE GET FAILED  key=%s  err=%s", key, exc)
        return None


def cache_set(key: str, value: Any, ttl: int) -> None:
    """Serialize value and store in Redis with a TTL (seconds)."""
    try:
        get_redis().setex(key, ttl, json.dumps(value))
        log.debug("CACHE SET   key=%s  ttl=%ds", key, ttl)
    except Exception as exc:
        log.warning("CACHE SET FAILED  key=%s  err=%s", key, exc)


def cache_delete(key: str) -> None:
    """Evict a single cache key."""
    try:
        get_redis().delete(key)
        log.debug("CACHE DEL   key=%s", key)
    except Exception as exc:
        log.warning("CACHE DEL FAILED  key=%s  err=%s", key, exc)


def cache_delete_pattern(pattern: str) -> None:
    """
    Evict all keys matching a glob pattern.

    Uses SCAN instead of KEYS so it never blocks the Redis event loop —
    KEYS is O(N) and halts all other Redis operations while it runs.
    SCAN iterates in small batches (count=100) and is safe in production.
    """
    try:
        r = get_redis()
        cursor, deleted = 0, 0
        while True:
            cursor, keys = r.scan(cursor, match=pattern, count=100)
            if keys:
                r.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        log.debug("CACHE DEL PATTERN  pattern=%s  deleted=%d key(s)", pattern, deleted)
    except Exception as exc:
        log.warning("CACHE DEL PATTERN FAILED  pattern=%s  err=%s", pattern, exc)
