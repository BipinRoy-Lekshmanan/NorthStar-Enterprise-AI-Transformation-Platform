"""Request-ID + response-timing middleware (Milestone 7).

Every response carries the same `request_id` that error envelopes and
audit events use, so a user-visible error, a server log line, and an
audit record can all be correlated by one identifier.
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"
RESPONSE_TIME_HEADER = "X-Response-Time-Ms"


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[RESPONSE_TIME_HEADER] = f"{duration_ms:.1f}"
        return response
