"""API-boundary wrapper over `app.resilience.idempotency` (Milestone 8).

Routes call `check_idempotency()` before doing any real work and
`save_idempotent_response()` after a successful call -- both are no-ops
(return `None` / do nothing) when the caller didn't send an
`Idempotency-Key` header, so every pre-existing caller is unaffected.
"""

from __future__ import annotations

from fastapi import Request

from app.api.errors import ApiError, ErrorCode
from app.resilience.idempotency import (
    IdempotencyKeyReusedError,
    IdempotencyStore,
    StoredResponse,
    hash_request_body,
)

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
MAX_IDEMPOTENCY_KEY_LENGTH = 200


def check_idempotency(
    request: Request, store: IdempotencyStore, endpoint: str, request_body: dict,
) -> StoredResponse | None:
    """Returns a `StoredResponse` the route should return directly
    (instead of doing any real work) when this exact `(key, endpoint,
    request_body)` was already handled. Returns `None` when the caller
    should proceed normally."""
    key = request.headers.get(IDEMPOTENCY_KEY_HEADER)
    if not key:
        return None
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ApiError(
            400, ErrorCode.VALIDATION_ERROR,
            f"{IDEMPOTENCY_KEY_HEADER} must be at most {MAX_IDEMPOTENCY_KEY_LENGTH} characters.",
        )
    try:
        return store.get_cached_response(key, endpoint, hash_request_body(request_body))
    except IdempotencyKeyReusedError as exc:
        raise ApiError(409, ErrorCode.IDEMPOTENCY_KEY_REUSED, str(exc)) from exc


def save_idempotent_response(
    request: Request, store: IdempotencyStore, endpoint: str, request_body: dict,
    status_code: int, body: dict,
) -> None:
    key = request.headers.get(IDEMPOTENCY_KEY_HEADER)
    if not key:
        return
    store.save_response(key, endpoint, hash_request_body(request_body), status_code, body)
