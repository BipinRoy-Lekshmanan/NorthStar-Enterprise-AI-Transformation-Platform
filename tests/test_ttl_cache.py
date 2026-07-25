"""Tests for `app.cache.ttl_cache.TTLCache` (Milestone 8)."""

import pytest

from app.cache.ttl_cache import TTLCache


def test_rejects_non_positive_ttl():
    with pytest.raises(ValueError, match="ttl_seconds"):
        TTLCache(ttl_seconds=0)
    with pytest.raises(ValueError, match="ttl_seconds"):
        TTLCache(ttl_seconds=-1)


def test_get_on_missing_key_returns_none():
    cache = TTLCache(ttl_seconds=10)
    assert cache.get("missing") is None


def test_set_then_get_returns_the_value():
    cache = TTLCache(ttl_seconds=10)
    cache.set("key", {"a": 1})
    assert cache.get("key") == {"a": 1}


def test_entry_expires_after_ttl():
    now = [0.0]
    cache = TTLCache(ttl_seconds=5, clock=lambda: now[0])
    cache.set("key", "value")

    now[0] = 4.9
    assert cache.get("key") == "value"

    now[0] = 5.1
    assert cache.get("key") is None


def test_get_or_compute_only_calls_compute_once_within_ttl():
    now = [0.0]
    cache = TTLCache(ttl_seconds=10, clock=lambda: now[0])
    calls = []

    def _compute():
        calls.append(1)
        return "computed"

    assert cache.get_or_compute("key", _compute) == "computed"
    assert cache.get_or_compute("key", _compute) == "computed"
    assert len(calls) == 1

    now[0] = 10.1
    assert cache.get_or_compute("key", _compute) == "computed"
    assert len(calls) == 2


def test_invalidate_a_single_key():
    cache = TTLCache(ttl_seconds=10)
    cache.set("a", 1)
    cache.set("b", 2)

    cache.invalidate("a")

    assert cache.get("a") is None
    assert cache.get("b") == 2


def test_invalidate_with_no_key_clears_everything():
    cache = TTLCache(ttl_seconds=10)
    cache.set("a", 1)
    cache.set("b", 2)

    cache.invalidate()

    assert cache.get("a") is None
    assert cache.get("b") is None
    assert cache.size() == 0


def test_size_reflects_live_entries():
    cache = TTLCache(ttl_seconds=10)
    assert cache.size() == 0
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.size() == 2


def test_keys_can_be_arbitrary_hashables_not_just_strings():
    cache = TTLCache(ttl_seconds=10)
    key = (1, "a", frozenset({1, 2}))
    cache.set(key, "value")
    assert cache.get(key) == "value"
