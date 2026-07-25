"""Tests for `app.resilience.retry.retry_with_backoff` (Milestone 8).
Uses an injectable `sleep` so every test runs at full speed with zero
real delay -- and doubles as proof the function actually calls `sleep`
with the expected (bounded, jittered) values.
"""

from __future__ import annotations

import pytest

from app.resilience.retry import retry_with_backoff


class _RetryableError(Exception):
    pass


class _NonRetryableError(Exception):
    pass


def test_succeeds_on_first_attempt_without_sleeping():
    sleeps = []
    result = retry_with_backoff(lambda: "ok", retryable=(_RetryableError,), sleep=sleeps.append)
    assert result == "ok"
    assert sleeps == []


def test_retries_until_success():
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise _RetryableError("transient")
        return "recovered"

    sleeps = []
    result = retry_with_backoff(flaky, max_retries=5, retryable=(_RetryableError,), sleep=sleeps.append, jitter=False)
    assert result == "recovered"
    assert attempts["count"] == 3
    assert len(sleeps) == 2  # two failures before the third, successful attempt


def test_raises_after_exhausting_retries():
    def always_fails():
        raise _RetryableError("still broken")

    with pytest.raises(_RetryableError):
        retry_with_backoff(always_fails, max_retries=2, retryable=(_RetryableError,), sleep=lambda _: None)


def test_non_retryable_exception_propagates_immediately_without_sleeping():
    sleeps = []

    def fails_hard():
        raise _NonRetryableError("do not retry this")

    with pytest.raises(_NonRetryableError):
        retry_with_backoff(fails_hard, retryable=(_RetryableError,), sleep=sleeps.append)
    assert sleeps == []  # never even entered the retry loop


def test_backoff_grows_exponentially_and_is_capped(monkeypatch):
    def always_fails():
        raise _RetryableError("x")

    sleeps = []
    with pytest.raises(_RetryableError):
        retry_with_backoff(
            always_fails, max_retries=4, base_delay_seconds=1.0, max_delay_seconds=3.0,
            jitter=False, retryable=(_RetryableError,), sleep=sleeps.append,
        )
    # 1.0, 2.0, 3.0 (capped from 4.0), 3.0 (capped from 8.0)
    assert sleeps == [1.0, 2.0, 3.0, 3.0]


def test_jitter_keeps_delay_within_half_to_one_and_a_half_times_base():
    def always_fails():
        raise _RetryableError("x")

    sleeps = []
    with pytest.raises(_RetryableError):
        retry_with_backoff(
            always_fails, max_retries=1, base_delay_seconds=2.0, jitter=True,
            retryable=(_RetryableError,), sleep=sleeps.append,
        )
    assert len(sleeps) == 1
    assert 1.0 <= sleeps[0] < 3.0  # 2.0 * [0.5, 1.5)
