"""A tiny in-memory stand-in for the Redis surface the application uses.

The backend treats Redis as a cache and a fixed-window rate-limit store, and it
*deliberately fails open* when Redis is down. Driving the whole suite with a
real (or absent) Redis would make cache-dependent behaviour — refresh-token
blacklisting, rate limits, the identity cache — untestable, so this fake
implements exactly the few commands the app calls:

    get, set(ex=...), delete, scan_iter(match=...), incr, ttl, expire,
    ping, pipeline().incr().ttl().execute()

It is intentionally simple (no real expiry sweeping beyond a lazy check) and
lives only under ``tests/``.
"""

from __future__ import annotations

import fnmatch
import time


class _FakePipeline:
    def __init__(self, store: "FakeRedis") -> None:
        self._store = store
        self._ops: list[tuple[str, str]] = []

    def incr(self, key: str) -> "_FakePipeline":
        self._ops.append(("incr", key))
        return self

    def ttl(self, key: str) -> "_FakePipeline":
        self._ops.append(("ttl", key))
        return self

    def execute(self) -> list:
        results = []
        for op, key in self._ops:
            results.append(self._store.incr(key) if op == "incr" else self._store.ttl(key))
        self._ops.clear()
        return results


class FakeRedis:
    """A minimal in-memory Redis good enough for the cache + rate limiter."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._expiry: dict[str, float] = {}

    # -- internals ----------------------------------------------------------
    def _purge(self, key: str) -> None:
        expires = self._expiry.get(key)
        if expires is not None and expires < time.time():
            self._data.pop(key, None)
            self._expiry.pop(key, None)

    # -- commands -----------------------------------------------------------
    def ping(self) -> bool:
        return True

    def get(self, key: str):
        self._purge(key)
        return self._data.get(key)

    def set(self, key: str, value, ex=None):
        self._data[key] = value if isinstance(value, str) else str(value)
        if ex:
            self._expiry[key] = time.time() + int(ex)
        else:
            self._expiry.pop(key, None)
        return True

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self._data:
                removed += 1
            self._data.pop(key, None)
            self._expiry.pop(key, None)
        return removed

    def scan_iter(self, match: str = "*", count: int = 500):
        for key in list(self._data):
            self._purge(key)
            if key in self._data and fnmatch.fnmatch(key, match):
                yield key

    def incr(self, key: str) -> int:
        self._purge(key)
        try:
            value = int(self._data.get(key, 0))
        except (TypeError, ValueError):
            value = 0
        value += 1
        self._data[key] = str(value)
        return value

    def ttl(self, key: str) -> int:
        self._purge(key)
        expires = self._expiry.get(key)
        if expires is None:
            return -1
        return max(int(expires - time.time()), 0)

    def expire(self, key: str, seconds: int) -> bool:
        if key in self._data:
            self._expiry[key] = time.time() + int(seconds)
            return True
        return False

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        return _FakePipeline(self)
