"""FastAPI dependencies resolving the current user and enforcing role
requirements (Milestone 7-8).

`get_current_user` is the single place that turns an `X-API-Key` header
into a `User` -- it raises a 401 `ApiError` when the header is missing,
unrecognized, or belongs to a disabled user. `require_role` composes on
top of it via `Depends`, so a 403 is only ever raised once a user has
already been successfully resolved -- the 401-vs-403 split falls out of
dependency ordering, not conditional logic.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import Depends, Header, Request

from app.api.errors import ApiError, ErrorCode
from app.auth.roles import Role, role_at_least
from app.auth.users import User
from app.telemetry.metrics import auth_failures_total

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-API-Key"


def _redacted_key(api_key: str) -> str:
    """A stable, non-reversible identifier for a failed-auth log line --
    never the raw key (a mistyped or misdirected *real* key could
    otherwise leak into the log), just enough to correlate repeated
    attempts."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


def _find_user_by_api_key(users: dict[str, User], api_key: str) -> User | None:
    """Constant-time key comparison: every configured key is checked via
    `hmac.compare_digest` (never `==`, and never a dict lookup keyed
    directly by the raw client-supplied string), and every key is
    checked -- no short-circuit on the first match -- so total request
    time leaks neither how close a wrong key is to a valid one nor
    which key matched."""
    api_key_bytes = api_key.encode("utf-8")
    matched: User | None = None
    for candidate_key, user in users.items():
        if hmac.compare_digest(candidate_key.encode("utf-8"), api_key_bytes):
            matched = user
    return matched


def get_current_user(
    request: Request, x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER)
) -> User:
    if not x_api_key:
        auth_failures_total.labels(reason="missing_header").inc()
        logger.warning("Authentication failed: missing X-API-Key header.")
        raise ApiError(401, ErrorCode.UNAUTHORIZED, "Missing X-API-Key header.")

    users: dict[str, User] = request.app.state.users
    user = _find_user_by_api_key(users, x_api_key)
    if user is None:
        auth_failures_total.labels(reason="invalid_key").inc()
        logger.warning("Authentication failed: unrecognized API key (%s).", _redacted_key(x_api_key))
        raise ApiError(401, ErrorCode.UNAUTHORIZED, "Invalid API key.")

    if not user.enabled:
        auth_failures_total.labels(reason="disabled_user").inc()
        logger.warning("Authentication failed: user '%s' is disabled.", user.username)
        # Deliberately the same message/code as an unrecognized key --
        # a disabled account should be indistinguishable from a wrong
        # one to whoever is holding its key.
        raise ApiError(401, ErrorCode.UNAUTHORIZED, "Invalid API key.")

    return user


def require_role(minimum: Role):
    """Dependency factory: `Depends(require_role(Role.REVIEWER))`."""

    def _check(user: User = Depends(get_current_user)) -> User:
        if not role_at_least(user.role, minimum):
            raise ApiError(
                403,
                ErrorCode.FORBIDDEN,
                f"This action requires the '{minimum.value}' role or higher; you have '{user.role.value}'.",
                details={"required_role": minimum.value, "actual_role": user.role.value},
            )
        return user

    return _check
