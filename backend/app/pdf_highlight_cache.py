"""Highlighted PDF cache and rate limit. Uses Redis when REDIS_URL is set (shared across workers), else in-memory."""
from __future__ import annotations
import threading
import time
from collections import deque
from typing import Optional, Protocol

from .config import (
    REDIS_URL,
    PDF_HIGHLIGHT_CACHE_TTL_SECONDS,
    PDF_HIGHLIGHT_CACHE_MAX_ENTRIES,
    PDF_HIGHLIGHT_RATE_LIMIT_PER_DOC,
    PDF_HIGHLIGHT_CACHE_REDIS_PREFIX,
    PDF_HIGHLIGHT_RATELIMIT_REDIS_PREFIX,
)


def make_cache_key(
    doc_id: str, page: int, hl_left: float, hl_bottom: float, hl_right: float, hl_top: float
) -> str:
    return f"{doc_id}:{page}:{hl_left}:{hl_bottom}:{hl_right}:{hl_top}"


class HighlightCache(Protocol):
    def get(self, key: str) -> Optional[bytes]: ...
    def set(self, key: str, value: bytes) -> None: ...


class HighlightRateLimit(Protocol):
    def allow(self, doc_id: str) -> bool: ...


# --- In-memory implementations (single process) ---


class MemoryHighlightCache:
    """TTL cache for highlighted PDF bytes. Thread-safe, max size with eviction by expiry."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, tuple[bytes, float]] = {}

    def get(self, key: str) -> Optional[bytes]:
        with self._lock:
            if key not in self._data:
                return None
            data, expiry = self._data[key]
            if time.time() > expiry:
                del self._data[key]
                return None
            return data

    def set(self, key: str, value: bytes) -> None:
        expiry = time.time() + PDF_HIGHLIGHT_CACHE_TTL_SECONDS
        with self._lock:
            self._data[key] = (value, expiry)
            if len(self._data) > PDF_HIGHLIGHT_CACHE_MAX_ENTRIES:
                now = time.time()
                expired = [k for k, (_, ex) in self._data.items() if ex < now]
                for k in expired:
                    del self._data[k]
                while len(self._data) > PDF_HIGHLIGHT_CACHE_MAX_ENTRIES:
                    oldest_key = min(self._data, key=lambda k: self._data[k][1])
                    del self._data[oldest_key]


class MemoryHighlightRateLimit:
    """Per-doc rate limit: N requests per minute. Thread-safe. Bounded: one deque per doc, maxlen=limit."""

    def __init__(self):
        self._lock = threading.Lock()
        self._doc_timestamps: dict[str, deque] = {}
        self._window_sec = 60.0

    def allow(self, doc_id: str) -> bool:
        now = time.time()
        cutoff = now - self._window_sec
        with self._lock:
            if doc_id not in self._doc_timestamps:
                self._doc_timestamps[doc_id] = deque(maxlen=PDF_HIGHLIGHT_RATE_LIMIT_PER_DOC)
            ts_deque = self._doc_timestamps[doc_id]
            while ts_deque and ts_deque[0] < cutoff:
                ts_deque.popleft()
            if len(ts_deque) >= PDF_HIGHLIGHT_RATE_LIMIT_PER_DOC:
                return False
            ts_deque.append(now)
            return True


# --- Redis implementations (shared across API workers) ---


class RedisHighlightCache:
    """Redis-backed cache for highlighted PDF bytes. Shared across all API processes."""

    def __init__(self):
        import redis
        self._client = redis.Redis.from_url(REDIS_URL, decode_responses=False)
        self._prefix = PDF_HIGHLIGHT_CACHE_REDIS_PREFIX
        self._ttl = PDF_HIGHLIGHT_CACHE_TTL_SECONDS

    def _key(self, key: str) -> str:
        return self._prefix + key

    def get(self, key: str) -> Optional[bytes]:
        data = self._client.get(self._key(key))
        return data

    def set(self, key: str, value: bytes) -> None:
        self._client.setex(self._key(key), self._ttl, value)


class RedisHighlightRateLimit:
    """Redis-backed per-doc rate limit. Shared across all API processes."""

    def __init__(self):
        import redis
        self._client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        self._prefix = PDF_HIGHLIGHT_RATELIMIT_REDIS_PREFIX
        self._limit = PDF_HIGHLIGHT_RATE_LIMIT_PER_DOC
        self._window_sec = 60

    def _key(self, doc_id: str) -> str:
        return self._prefix + doc_id

    def allow(self, doc_id: str) -> bool:
        k = self._key(doc_id)
        pipe = self._client.pipeline()
        pipe.incr(k)
        pipe.expire(k, self._window_sec)
        results = pipe.execute()
        count = results[0]
        return count <= self._limit


# --- Singleton: Redis when REDIS_URL set, else in-memory ---

_highlight_cache: Optional[HighlightCache] = None
_highlight_rate_limit: Optional[HighlightRateLimit] = None


def get_highlight_cache() -> HighlightCache:
    global _highlight_cache
    if _highlight_cache is None:
        if REDIS_URL:
            _highlight_cache = RedisHighlightCache()
        else:
            _highlight_cache = MemoryHighlightCache()
    return _highlight_cache


def get_highlight_rate_limit() -> HighlightRateLimit:
    global _highlight_rate_limit
    if _highlight_rate_limit is None:
        if REDIS_URL:
            _highlight_rate_limit = RedisHighlightRateLimit()
        else:
            _highlight_rate_limit = MemoryHighlightRateLimit()
    return _highlight_rate_limit
