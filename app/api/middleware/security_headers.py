"""Security response headers (Milestone 8) -- stamped on every response,
including error/rejection responses from inner middleware (rate limit,
request-size limit), so this must sit outermost in the middleware stack.

`setdefault` is used throughout: a route that deliberately sets one of
these headers itself is never silently overridden.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    # Harmless (and ignored by browsers) over plain HTTP -- only takes
    # effect once a TLS-terminating proxy is in front of this API, which
    # is exactly the deployment this header exists for.
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Permitted-Cross-Domain-Policies": "none",
}

# The built-in Swagger UI (/docs) and ReDoc (/redoc) pages load their own
# JS/CSS from a CDN -- a strict "no external resources" CSP would break
# them. That relaxed policy is scoped to just those two HTML pages; every
# JSON API response (everything else) gets the strict policy.
_DOCS_PATHS = ("/docs", "/redoc")
_STRICT_CSP = "default-src 'none'; frame-ancestors 'none'"
_DOCS_CSP = (
    "default-src 'self'; img-src 'self' data: fastapi.tiangolo.com; "
    "script-src 'self' cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' cdn.jsdelivr.net"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        is_docs_page = any(request.url.path.startswith(prefix) for prefix in _DOCS_PATHS)
        response.headers.setdefault("Content-Security-Policy", _DOCS_CSP if is_docs_page else _STRICT_CSP)
        return response
