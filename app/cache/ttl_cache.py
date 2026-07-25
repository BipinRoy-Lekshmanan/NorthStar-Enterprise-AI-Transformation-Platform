"""Generic in-process TTL cache (Milestone 8).

Deliberately simple: a single-process, in-memory dict with per-key
expiry -- no distributed cache, no LRU eviction (entries are short-
lived and the key space here is small/bounded by construction, not
unbounded user input). Matches this milestone's "simple in-process"
scope, the same one `RateLimitMiddleware`'s own docstring documents.

Read-only re-computation (`build_catalog()` re-running the whole
Milestone 1 ingestion pipeline on every call) is the intended use --
see `app.api.services.knowledge_service`. Caching alone is not enough
to stay correct, though: whatever calls that also *mutates* the
underlying data (ingest/index/rebuild) must explicitly invalidate the
relevant key, since this cache has no way to know the data changed
out from under it.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Generic, TypeVar

_T = TypeVar("_T")


@dataclass
class _Entry(Generic[_T]):
    value: _T
    expires_at: float


class TTLCache(Generic[_T]):
    def __init__(self, ttl_seconds: float, *, clock: Callable[[], float] = time.monotonic):
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}.")
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[Hashable, _Entry[_T]] = {}

    def get(self, key: Hashable) -> _T | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at < self._clock():
                del self._entries[key]
                return None
            return entry.value

    def set(self, key: Hashable, value: _T) -> None:
        with self._lock:
            self._entries[key] = _Entry(value=value, expires_at=self._clock() + self._ttl_seconds)

    def get_or_compute(self, key: Hashable, compute: Callable[[], _T]) -> _T:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = compute()
        self.set(key, value)
        return value

    def invalidate(self, key: Hashable | None = None) -> None:
        """Clears one key, or the entire cache when `key` is `None`."""
        with self._lock:
            if key is None:
                self._entries.clear()
            else:
                self._entries.pop(key, None)

    def size(self) -> int:
        with self._lock:
            return len(self._entries)
