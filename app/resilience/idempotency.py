"""Idempotency-key replay support (Milestone 8), backed by the
`idempotency_records` SQLite table (`app.db.models.IdempotencyRecord`).

Deliberately scoped to *replay-on-retry*: the same `(Idempotency-Key,
endpoint)` pair returns the exact response the first call produced,
without re-running the operation. It does not track "in progress"
state -- a genuinely concurrent duplicate (two requests with the same
key arriving at the same moment) is instead caught by `LockRegistry`
on the endpoints that already have one (workflow/approval execution
locks, the knowledge rebuild lock); idempotency here is purely about a
client retrying *after* a prior call already completed (e.g. following
a timeout on their end).

No FastAPI/`ApiError` dependency here, matching `app.resilience.retry`/
`circuit_breaker`/`concurrency` -- the API-layer wrapper that turns
`IdempotencyKeyReusedError` into a 409 response lives in
`app.api.services.idempotency_service`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, sessionmaker

from app.db.engine import session_scope
from app.db.models import IdempotencyRecord

DEFAULT_IDEMPOTENCY_TTL = timedelta(hours=24)


def hash_request_body(body: dict) -> str:
    """A stable hash of a JSON-serializable request body -- used to
    detect a client reusing the same key for a *different* request
    (a bug, not a retry)."""
    canonical = json.dumps(body, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    body: dict


class IdempotencyKeyReusedError(Exception):
    def __init__(self, key: str):
        super().__init__(f"Idempotency-Key '{key}' was already used with a different request body.")
        self.key = key


def _as_aware_utc(value: datetime) -> datetime:
    """SQLite has no native timezone type -- SQLAlchemy round-trips a
    tz-aware `DateTime(timezone=True)` column back as naive on some
    driver/version combinations. Treat a naive value as UTC (the only
    timezone anything in this module ever writes) rather than comparing
    naive-vs-aware and raising."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class IdempotencyStore:
    """Thin, session-per-call wrapper -- consistent with `AuditStore`/
    `WorkflowStore` never holding a connection open between calls."""

    def __init__(self, session_factory: sessionmaker[Session], ttl: timedelta = DEFAULT_IDEMPOTENCY_TTL):
        self._session_factory = session_factory
        self._ttl = ttl

    def get_cached_response(self, key: str, endpoint: str, request_hash: str) -> StoredResponse | None:
        """Returns the previously-stored response for `(key, endpoint)`,
        or `None` if there is no live (unexpired) record -- the caller
        should proceed normally in that case. Raises
        `IdempotencyKeyReusedError` if the key was already used on this
        endpoint with a *different* request body."""
        now = datetime.now(timezone.utc)
        with session_scope(self._session_factory) as session:
            record = (
                session.query(IdempotencyRecord)
                .filter_by(idempotency_key=key, endpoint=endpoint)
                .one_or_none()
            )
            if record is None or _as_aware_utc(record.expires_at) < now:
                return None
            if record.request_hash != request_hash:
                raise IdempotencyKeyReusedError(key)
            return StoredResponse(status_code=record.response_status, body=record.response_body)

    def save_response(self, key: str, endpoint: str, request_hash: str, status_code: int, body: dict) -> None:
        """Upserts -- a retried key on an expired record simply
        overwrites it rather than hitting the unique-constraint path."""
        now = datetime.now(timezone.utc)
        with session_scope(self._session_factory) as session:
            record = (
                session.query(IdempotencyRecord)
                .filter_by(idempotency_key=key, endpoint=endpoint)
                .one_or_none()
            )
            if record is None:
                session.add(
                    IdempotencyRecord(
                        idempotency_key=key, endpoint=endpoint, request_hash=request_hash,
                        response_status=status_code, response_body=body,
                        created_at=now, expires_at=now + self._ttl,
                    )
                )
            else:
                record.request_hash = request_hash
                record.response_status = status_code
                record.response_body = body
                record.created_at = now
                record.expires_at = now + self._ttl
