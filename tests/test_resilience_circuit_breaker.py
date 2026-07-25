"""Tests for `app.resilience.circuit_breaker.CircuitBreaker` (Milestone 8).
Uses an injectable `clock` so the half-open reset-timeout transition is
deterministic and instant, never a real `time.sleep`.
"""

from __future__ import annotations

import pytest

from app.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _breaker(**overrides) -> CircuitBreaker:
    clock = _FakeClock()
    defaults = dict(name="test-provider", failure_threshold=3, reset_timeout_seconds=10.0, clock=clock)
    defaults.update(overrides)
    breaker = CircuitBreaker(**defaults)
    breaker._test_clock = clock  # stash for tests that need to advance time
    return breaker


def test_starts_closed():
    breaker = _breaker()
    assert breaker.state == CircuitState.CLOSED


def test_successful_calls_keep_it_closed():
    breaker = _breaker()
    for _ in range(10):
        assert breaker.call(lambda: "ok") == "ok"
    assert breaker.state == CircuitState.CLOSED


def test_opens_after_reaching_the_failure_threshold():
    breaker = _breaker(failure_threshold=3)

    def fails():
        raise RuntimeError("boom")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            breaker.call(fails)

    assert breaker.state == CircuitState.OPEN


def test_open_breaker_rejects_calls_without_invoking_the_function():
    breaker = _breaker(failure_threshold=1)
    calls = {"count": 0}

    def fails():
        calls["count"] += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        breaker.call(fails)
    assert breaker.state == CircuitState.OPEN

    with pytest.raises(CircuitBreakerOpenError):
        breaker.call(fails)
    assert calls["count"] == 1  # the second call never actually ran `fails`


def test_transitions_to_half_open_after_reset_timeout():
    breaker = _breaker(failure_threshold=1, reset_timeout_seconds=10.0)
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert breaker.state == CircuitState.OPEN

    breaker._test_clock.advance(5.0)
    assert breaker.state == CircuitState.OPEN  # not yet

    breaker._test_clock.advance(5.1)
    assert breaker.state == CircuitState.HALF_OPEN


def test_half_open_success_closes_the_breaker():
    breaker = _breaker(failure_threshold=1, reset_timeout_seconds=10.0)
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    breaker._test_clock.advance(11.0)
    assert breaker.state == CircuitState.HALF_OPEN

    assert breaker.call(lambda: "recovered") == "recovered"
    assert breaker.state == CircuitState.CLOSED


def test_half_open_failure_reopens_the_breaker():
    breaker = _breaker(failure_threshold=1, reset_timeout_seconds=10.0)
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    breaker._test_clock.advance(11.0)
    assert breaker.state == CircuitState.HALF_OPEN

    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("still broken")))
    assert breaker.state == CircuitState.OPEN


def test_a_single_failure_below_threshold_does_not_open_it():
    breaker = _breaker(failure_threshold=3)
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert breaker.state == CircuitState.CLOSED


def test_failure_exceptions_narrows_what_counts_as_a_failure():
    """A permanent config error shouldn't trip the same breaker as a
    transient failure -- it should propagate with its original type,
    every time, never masked behind CircuitBreakerOpenError."""
    breaker = _breaker(failure_threshold=1)

    class ConfigError(Exception):
        pass

    class TransientError(Exception):
        pass

    def fails_with_config_error():
        raise ConfigError("bad api key")

    for _ in range(5):
        with pytest.raises(ConfigError):
            breaker.call(fails_with_config_error, failure_exceptions=(TransientError,))
    assert breaker.state == CircuitState.CLOSED  # never counted, never opened


def test_failure_exceptions_still_counts_matching_exceptions():
    breaker = _breaker(failure_threshold=1)

    class TransientError(Exception):
        pass

    def fails_transiently():
        raise TransientError("timeout")

    with pytest.raises(TransientError):
        breaker.call(fails_transiently, failure_exceptions=(TransientError,))
    assert breaker.state == CircuitState.OPEN


def test_success_resets_the_failure_count():
    breaker = _breaker(failure_threshold=3)
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert breaker.state == CircuitState.CLOSED  # 2 failures, threshold is 3

    breaker.call(lambda: "ok")  # resets the count

    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert breaker.state == CircuitState.CLOSED  # only 2 failures since the reset
