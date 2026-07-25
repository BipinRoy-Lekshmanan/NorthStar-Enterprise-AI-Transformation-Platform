"""Simple in-memory rate limiter, per category (Milestone 7-8).

A fixed 60-second sliding window per `(actor, category)` pair -- no
external cache or shared state, matching this milestone's explicit
scope ("a simple in-memory rate limiter", not a production distributed
one; see `docs/operations/deployment-architecture.md` for the
multi-instance caveat and the `RateLimiterBackend` extension point).
Counters reset on process restart and are not shared across multiple
worker processes.

Category is derived from the raw request path *before* routing
resolves (unlike `app.api.middleware.metrics`, which can afford to wait
for `request.scope["route"]` since it never needs to reject a request)
-- a prefix match against `app.api.version.API_PREFIX` is enough, since
every route under a given resource group shares one path prefix.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.errors import ErrorCode
from app.api.version import API_PREFIX
from app.telemetry.metrics import rate_limit_rejections_total

_WINDOW_SECONDS = 60.0

# Longest-prefix-first: "/knowledge/ingest" must be checked before the
# bare "/knowledge" fallback would otherwise swallow it.
_CATEGORY_PREFIXES: tuple[tuple[str, str], ...] = (
    (f"{API_PREFIX}/query", "query"),
    (f"{API_PREFIX}/advisors", "advisor"),
    (f"{API_PREFIX}/workflows", "workflow"),
    (f"{API_PREFIX}/approvals", "workflow"),
    (f"{API_PREFIX}/evaluation", "evaluation"),
    (f"{API_PREFIX}/knowledge/ingest", "administration"),
    (f"{API_PREFIX}/knowledge/index", "administration"),
    (f"{API_PREFIX}/knowledge/rebuild", "administration"),
    (f"{API_PREFIX}/operations/rebuild", "administration"),
    (f"{API_PREFIX}/platform/audit", "administration"),
)
_DEFAULT_CATEGORY = "default"


def categorize(path: str) -> str:
    for prefix, category in _CATEGORY_PREFIXES:
        if path.startswith(prefix):
            return category
    return _DEFAULT_CATEGORY


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int, category_limits: dict[str, int] | None = None):
        super().__init__(app)
        self._limits = {_DEFAULT_CATEGORY: requests_per_minute, **(category_limits or {})}
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        actor = request.headers.get("x-api-key") or (request.client.host if request.client else "unknown")
        category = categorize(request.url.path)
        limit = self._limits.get(category, self._limits[_DEFAULT_CATEGORY])

        now = time.monotonic()
        hits = self._hits[(actor, category)]
        while hits and now - hits[0] > _WINDOW_SECONDS:
            hits.popleft()

        if len(hits) >= limit:
            retry_after_seconds = max(1, int(_WINDOW_SECONDS - (now - hits[0])) + 1)
            rate_limit_rejections_total.labels(category=category).inc()
            self._audit_rejection(request, actor, category)
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after_seconds)},
                content={
                    "error": {
                        "code": ErrorCode.RATE_LIMITED.value,
                        "message": (
                            f"Rate limit of {limit} requests per minute exceeded for category "
                            f"'{category}'. Retry after {retry_after_seconds}s."
                        ),
                        "details": {"category": category, "limit": limit, "retry_after_seconds": retry_after_seconds},
                        "request_id": None,
                    }
                },
            )

        hits.append(now)
        return await call_next(request)

    @staticmethod
    def _audit_rejection(request: Request, actor: str, category: str) -> None:
        audit_store = getattr(request.app.state, "audit_store", None)
        if audit_store is None:
            return
        from app.audit.models import AuditEvent

        audit_store.record(
            AuditEvent(
                request_id=getattr(request.state, "request_id", None),
                actor=actor,
                role="unknown",
                action="rate_limit_exceeded",
                resource_type="rate_limit_category",
                resource_id=category,
                outcome="rejected",
                metadata={"path": request.url.path},
            )
        )
