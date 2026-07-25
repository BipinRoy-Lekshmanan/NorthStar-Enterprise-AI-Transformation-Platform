"""Request-ID + response-timing middleware (Milestones 7-8).

Every response carries the same `request_id` that error envelopes and
audit events use, so a user-visible error, a server log line, and an
audit record can all be correlated by one identifier. Milestone 8 adds:
a length cap on an incoming client-supplied id (an unbounded header
value is both a memory-abuse vector and pollutes logs/metrics), and
propagation into `app.config.logging`'s contextvar so every log line
emitted anywhere during this request -- not just ones with direct
access to `request.state` -- carries the same id.
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.config.logging import reset_request_id, set_request_id

REQUEST_ID_HEADER = "X-Request-ID"
RESPONSE_TIME_HEADER = "X-Response-Time-Ms"

# Generous enough for a UUID hex (32 chars) plus any reasonable
# caller-supplied trace id, small enough to reject abuse/junk headers.
MAX_REQUEST_ID_LENGTH = 128


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        if incoming and 0 < len(incoming) <= MAX_REQUEST_ID_LENGTH:
            request_id = incoming
        else:
            request_id = uuid.uuid4().hex
        request.state.request_id = request_id

        token = set_request_id(request_id)
        try:
            start = time.perf_counter()
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start) * 1000
        finally:
            reset_request_id(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[RESPONSE_TIME_HEADER] = f"{duration_ms:.1f}"
        return response
