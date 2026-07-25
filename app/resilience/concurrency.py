"""Bounded concurrency controls (Milestone 8).

Two distinct primitives for two distinct problems:

- `LockRegistry` -- named, non-blocking, mutually-exclusive locks. Used
  where *two concurrent attempts at the same operation* would be a
  correctness bug, not just a performance concern (a second full
  rebuild starting before the first finishes; two requests both trying
  to resume or approve the same execution). `try_acquire()` never
  blocks -- a caller that can't get the lock is rejected immediately
  with `ConcurrencyConflictError`, matching "return clear conflict
  responses" rather than silently queuing behind an in-flight
  operation.
- `BoundedConcurrency` -- a named, bounded semaphore capping how many
  concurrent calls of a given *kind* may run at once (e.g. concurrent
  OpenAI calls). Blocks the caller briefly rather than rejecting --
  a burst of legitimate concurrent requests should queue, not fail;
  the rate limiter is the reject-outright layer for abuse.

Both are process-local (matching `CircuitBreaker`'s and
`RateLimitMiddleware`'s own documented single-process scope) -- see
`docs/operations/deployment-architecture.md` for the multi-instance
caveat.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class ConcurrencyConflictError(Exception):
    """Raised when a caller tries to acquire a named lock that's already held."""

    def __init__(self, name: str):
        super().__init__(f"Operation '{name}' is already in progress.")
        self.name = name


class LockRegistry:
    def __init__(self) -> None:
        self._registry_lock = threading.Lock()
        self._held: set[str] = set()

    @contextmanager
    def acquire(self, name: str) -> Iterator[None]:
        with self._registry_lock:
            if name in self._held:
                raise ConcurrencyConflictError(name)
            self._held.add(name)
        try:
            yield
        finally:
            with self._registry_lock:
                self._held.discard(name)

    def is_locked(self, name: str) -> bool:
        with self._registry_lock:
            return name in self._held

    def active_locks(self) -> list[str]:
        with self._registry_lock:
            return sorted(self._held)


class BoundedConcurrency:
    def __init__(self, max_concurrent: int) -> None:
        if max_concurrent <= 0:
            raise ValueError(f"max_concurrent must be positive, got {max_concurrent}")
        self._semaphore = threading.Semaphore(max_concurrent)

    @contextmanager
    def acquire(self) -> Iterator[None]:
        self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()
