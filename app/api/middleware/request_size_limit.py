"""Rejects request bodies larger than a configured limit (Milestone 7).

Checked from the `Content-Length` header before any route or dependency
runs. A request without a well-formed positive `Content-Length` (e.g.
chunked transfer-encoding) is let through unchecked -- this is a
best-effort guard against obviously oversized bodies, not a hard
streaming cap.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.errors import ErrorCode


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                size = None
            if size is not None and size > self._max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": ErrorCode.VALIDATION_ERROR.value,
                            "message": (
                                f"Request body of {size} bytes exceeds the {self._max_bytes}-byte limit."
                            ),
                            "details": {},
                            "request_id": None,
                        }
                    },
                )
        return await call_next(request)
