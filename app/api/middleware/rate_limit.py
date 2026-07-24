"""Simple in-memory rate limiter (Milestone 7).

A fixed 60-second sliding window per API key (falling back to the
client's IP address if no key is present) -- no external cache or
shared state, matching this milestone's explicit scope ("a simple
in-memory rate limiter", not a production distributed one). Counters
reset on process restart and are not shared across multiple worker
processes.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.errors import ErrorCode

_WINDOW_SECONDS = 60.0


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int):
        super().__init__(app)
        self._limit = requests_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        key = request.headers.get("x-api-key") or (request.client.host if request.client else "unknown")
        now = time.monotonic()
        hits = self._hits[key]

        while hits and now - hits[0] > _WINDOW_SECONDS:
            hits.popleft()

        if len(hits) >= self._limit:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": ErrorCode.RATE_LIMITED.value,
                        "message": f"Rate limit of {self._limit} requests per minute exceeded. Try again shortly.",
                        "details": {},
                        "request_id": None,
                    }
                },
            )

        hits.append(now)
        return await call_next(request)
