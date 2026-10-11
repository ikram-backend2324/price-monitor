"""Per-domain token bucket.

Redis backend (atomic Lua script) for production; in-memory backend for tests
and single-process development.
"""

from __future__ import annotations

import threading
import time
from functools import lru_cache

from django.conf import settings

_LUA = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])      -- tokens per second
local capacity = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1]) or capacity
local ts = tonumber(data[2]) or now
tokens = math.min(capacity, tokens + (now - ts) * rate)
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
else
  wait = (1 - tokens) / rate
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, math.ceil(capacity / rate) + 60)
return tostring(wait)
"""


class MemoryBucket:
    def __init__(self) -> None:
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def acquire(self, key: str, per_minute: int, now: float | None = None) -> float:
        rate = max(per_minute, 1) / 60.0
        capacity = max(1.0, min(float(per_minute), 5.0))
        now = time.monotonic() if now is None else now
        with self._lock:
            tokens, ts = self._state.get(key, (capacity, now))
            tokens = min(capacity, tokens + (now - ts) * rate)
            if tokens >= 1:
                self._state[key] = (tokens - 1, now)
                return 0.0
            self._state[key] = (tokens, now)
            return (1 - tokens) / rate

    def reset(self) -> None:
        with self._lock:
            self._state.clear()


class RedisBucket:  # pragma: no cover - exercised in docker/integration
    def __init__(self, url: str) -> None:
        import redis

        self.client = redis.Redis.from_url(url)
        self.script = self.client.register_script(_LUA)

    def acquire(self, key: str, per_minute: int, now: float | None = None) -> float:
        rate = max(per_minute, 1) / 60.0
        capacity = max(1.0, min(float(per_minute), 5.0))
        result = self.script(keys=[f"pw:rl:{key}"], args=[rate, capacity, now or time.time()])
        return float(result)

    def reset(self) -> None:
        for key in self.client.scan_iter("pw:rl:*"):
            self.client.delete(key)


@lru_cache(maxsize=1)
def get_bucket():
    if settings.SCRAPER["RATE_LIMIT_BACKEND"] == "redis" and settings.REDIS_URL:
        return RedisBucket(settings.REDIS_URL)
    return MemoryBucket()


def acquire(domain: str, per_minute: int) -> float:
    """Take one token for ``domain``. Returns seconds to wait (0 = go now).

    The token is reserved even when a wait is returned, so callers must wait
    (or reschedule) rather than call again immediately.
    """
    return get_bucket().acquire(domain, per_minute)
