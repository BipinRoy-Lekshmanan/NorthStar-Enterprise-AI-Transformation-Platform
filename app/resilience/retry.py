"""Bounded retry with exponential backoff + jitter (Milestone 8).

Supersedes the retry helper originally in `app.embeddings.vectorizer`
(Milestone 2) -- centralized here so every network-backed provider
adapter (`OpenAIEmbeddingProvider`, `OpenAIModelProvider`) shares one
implementation instead of two near-identical copies, per this
milestone's "create structured retry and resilience configuration."
`FakeModelProvider`/`LocalHashingEmbeddingProvider` have no I/O failure
mode and never use this.

Only retry what's actually transient: the caller passes the exact
exception types worth retrying (rate limits, timeouts, transient
unavailability) -- invalid credentials, invalid requests, and
unsupported models are never in that set, so they propagate on the
first attempt.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

from app.telemetry.metrics import provider_retries_total

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY_SECONDS = 0.5
DEFAULT_MAX_DELAY_SECONDS = 30.0


def retry_with_backoff(
    func: Callable[[], _T],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
    jitter: bool = True,
    retryable: tuple[type[Exception], ...] = (),
    provider: str = "unknown",
    sleep: Callable[[float], None] = time.sleep,
) -> _T:
    """Runs `func`, retrying only `retryable` exceptions with capped
    exponential backoff. `jitter` applies "full jitter" (a random
    multiplier in `[0.5, 1.5)`) so many concurrent callers retrying the
    same failing dependency don't all retry in lockstep. `sleep` is
    injectable so tests can run this at full speed with zero real
    delay."""
    attempt = 0
    while True:
        try:
            return func()
        except retryable as exc:
            attempt += 1
            error_type = type(exc).__name__
            provider_retries_total.labels(provider=provider, error_type=error_type).inc()
            if attempt > max_retries:
                logger.warning(
                    "provider=%s retries exhausted after %d attempt(s): %s", provider, max_retries, exc,
                )
                raise
            delay = min(base_delay_seconds * (2 ** (attempt - 1)), max_delay_seconds)
            if jitter:
                # Retry-delay jitter only -- not security/crypto-sensitive.
                delay *= 0.5 + random.random()  # nosec B311
            logger.warning(
                "provider=%s call failed (%s), retrying in %.2fs (attempt %d/%d)",
                provider, error_type, delay, attempt, max_retries,
            )
            sleep(delay)
