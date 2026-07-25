"""In-process circuit breaker (Milestone 8).

`closed -> open -> half_open -> closed | open`, tracked per named
dependency (one instance per provider). **This is a single-process
implementation, not a distributed one** -- in a multi-instance
deployment, each replica tracks failures independently, so one
replica's breaker opening does not protect the others (see
`docs/operations/deployment-architecture.md` for the multi-instance
caveat). That scope limit is intentional for this milestone, not an
oversight.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Callable, TypeVar

from app.telemetry.metrics import circuit_breaker_state

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_RESET_TIMEOUT_SECONDS = 30.0

_STATE_METRIC_VALUES = {"closed": 0, "open": 1, "half_open": 2}


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    """Raised when a call is rejected because the breaker is open."""


class CircuitBreaker:
    def __init__(
        self, *, name: str, failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        reset_timeout_seconds: float = DEFAULT_RESET_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._name = name
        self._failure_threshold = failure_threshold
        self._reset_timeout_seconds = reset_timeout_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._record_state_metric()

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open_locked()
            return self._state

    def call(self, func: Callable[[], _T], *, failure_exceptions: tuple[type[Exception], ...] = (Exception,)) -> _T:
        """Runs `func` if the breaker allows it; raises
        `CircuitBreakerOpenError` immediately (never calling `func`) if
        open. A half-open call is the one "test request" allowed
        through before deciding whether to close or re-open.

        `failure_exceptions` narrows what actually counts against the
        breaker -- a permanent configuration error (bad API key,
        unsupported model) shouldn't trip the same breaker as a
        transient rate limit/timeout, since retrying or breaking the
        circuit doesn't help a config problem, and doing so would mask
        the specific, actionable error behind a generic "circuit
        breaker open" once the threshold is reached. Anything raised
        that doesn't match `failure_exceptions` still propagates
        normally; it just doesn't affect the breaker's state."""
        with self._lock:
            self._maybe_transition_to_half_open_locked()
            if self._state == CircuitState.OPEN:
                raise CircuitBreakerOpenError(f"Circuit breaker '{self._name}' is open.")

        try:
            result = func()
        except failure_exceptions:
            with self._lock:
                self._on_failure_locked()
            raise
        except Exception:
            raise
        else:
            with self._lock:
                self._on_success_locked()
            return result

    def _maybe_transition_to_half_open_locked(self) -> None:
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            if self._clock() - self._opened_at >= self._reset_timeout_seconds:
                self._state = CircuitState.HALF_OPEN
                logger.warning("circuit_breaker=%s open -> half_open (reset timeout elapsed)", self._name)
                self._record_state_metric()

    def _on_success_locked(self) -> None:
        was_half_open = self._state == CircuitState.HALF_OPEN
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = None
        if was_half_open:
            logger.info("circuit_breaker=%s half_open test succeeded -> closed", self._name)
        self._record_state_metric()

    def _on_failure_locked(self) -> None:
        self._failure_count += 1
        if self._state == CircuitState.HALF_OPEN:
            logger.warning("circuit_breaker=%s half_open test failed -> open", self._name)
            self._state = CircuitState.OPEN
            self._opened_at = self._clock()
        elif self._failure_count >= self._failure_threshold:
            logger.warning(
                "circuit_breaker=%s failure_threshold reached (%d/%d) -> open",
                self._name, self._failure_count, self._failure_threshold,
            )
            self._state = CircuitState.OPEN
            self._opened_at = self._clock()
        self._record_state_metric()

    def _record_state_metric(self) -> None:
        circuit_breaker_state.labels(provider=self._name).set(_STATE_METRIC_VALUES[self._state.value])
