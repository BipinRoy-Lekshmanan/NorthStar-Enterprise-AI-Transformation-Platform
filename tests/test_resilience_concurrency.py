"""Tests for `app.resilience.concurrency` (Milestone 8)."""

from __future__ import annotations

import threading
import time

import pytest

from app.resilience.concurrency import BoundedConcurrency, ConcurrencyConflictError, LockRegistry

# -- LockRegistry -----------------------------------------------------------------------------


def test_acquire_succeeds_when_not_held():
    registry = LockRegistry()
    with registry.acquire("rebuild"):
        assert registry.is_locked("rebuild")
    assert not registry.is_locked("rebuild")


def test_acquire_raises_when_already_held():
    registry = LockRegistry()
    with registry.acquire("rebuild"):
        with pytest.raises(ConcurrencyConflictError, match="rebuild"):
            with registry.acquire("rebuild"):
                pass


def test_lock_is_released_even_if_the_block_raises():
    registry = LockRegistry()
    with pytest.raises(ValueError):
        with registry.acquire("rebuild"):
            raise ValueError("boom")
    assert not registry.is_locked("rebuild")


def test_different_names_do_not_conflict():
    registry = LockRegistry()
    with registry.acquire("execution-1"):
        with registry.acquire("execution-2"):
            assert registry.is_locked("execution-1")
            assert registry.is_locked("execution-2")


def test_active_locks_lists_currently_held_names():
    registry = LockRegistry()
    with registry.acquire("a"):
        with registry.acquire("b"):
            assert registry.active_locks() == ["a", "b"]
    assert registry.active_locks() == []


def test_concurrent_threads_only_one_acquires_the_same_lock():
    registry = LockRegistry()
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        try:
            with registry.acquire("shared"):
                time.sleep(0.05)
                results.append("acquired")
        except ConcurrencyConflictError:
            results.append("rejected")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == ["acquired", "rejected"]


# -- BoundedConcurrency -----------------------------------------------------------------------------


def test_bounded_concurrency_allows_up_to_the_limit():
    bounded = BoundedConcurrency(max_concurrent=2)
    with bounded.acquire():
        with bounded.acquire():
            pass  # both acquired without blocking


def test_bounded_concurrency_blocks_beyond_the_limit():
    bounded = BoundedConcurrency(max_concurrent=1)
    acquired_second = threading.Event()

    def hold_and_release():
        with bounded.acquire():
            time.sleep(0.1)

    holder = threading.Thread(target=hold_and_release)
    holder.start()
    time.sleep(0.02)  # let the holder acquire first

    start = time.monotonic()
    with bounded.acquire():
        acquired_second.set()
    elapsed = time.monotonic() - start

    holder.join()
    assert acquired_second.is_set()
    assert elapsed >= 0.05  # had to wait for the holder to release


def test_bounded_concurrency_rejects_non_positive_limit():
    with pytest.raises(ValueError):
        BoundedConcurrency(max_concurrent=0)
