"""In-memory TTL cache for expensive responses."""

import time
from typing import Dict, Any, Optional


# ==============================================================================
# IN-MEMORY RESPONSE CACHE
# ==============================================================================
_RESPONSE_CACHE: Dict[str, Any] = {}
MAX_CACHE_ENTRIES = 1000


def get_cached_response(key: str) -> Optional[Any]:
    """Gets a cached response if it exists and has not expired."""
    if key in _RESPONSE_CACHE:
        val, expiry = _RESPONSE_CACHE[key]
        if time.time() < expiry:
            return val
        else:
            del _RESPONSE_CACHE[key]
    return None


def set_cached_response(key: str, value: Any, ttl: int = 300) -> None:
    """Sets a cached response with an expiration time; the cache never exceeds MAX_CACHE_ENTRIES."""
    if key not in _RESPONSE_CACHE and len(_RESPONSE_CACHE) >= MAX_CACHE_ENTRIES:
        now = time.time()
        for stale in [k for k, (_, expiry) in _RESPONSE_CACHE.items() if expiry <= now]:
            del _RESPONSE_CACHE[stale]
        if len(_RESPONSE_CACHE) >= MAX_CACHE_ENTRIES:
            del _RESPONSE_CACHE[next(iter(_RESPONSE_CACHE))]  # oldest inserted
    _RESPONSE_CACHE[key] = (value, time.time() + ttl)


def clear_response_cache() -> None:
    """Clears the entire response cache."""
    _RESPONSE_CACHE.clear()
