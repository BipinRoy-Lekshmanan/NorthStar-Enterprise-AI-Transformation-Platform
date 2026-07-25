"""API-level Prometheus instrumentation (Milestone 8).

Uses the *route template* (`/api/v1/workflows/executions/{execution_id}`),
not the raw resolved URL, as the `path` label -- the raw URL would put a
distinct execution/document/run id into a metric label for every
request, which is exactly the unbounded-cardinality mistake Prometheus
users are warned against. The template is only available on
`request.scope["route"]` once routing has resolved, i.e. after
`call_next()` returns.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.telemetry.metrics import (
    api_active_requests,
    api_errors_total,
    api_request_duration_seconds,
    api_requests_total,
)


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    # Unmatched route (404) -- fall back to a fixed label so a probe of
    # random paths can't still generate unbounded label values.
    return "unmatched"


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        api_active_requests.inc()
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            api_active_requests.dec()
        duration = time.perf_counter() - start

        path = _route_path(request)
        method = request.method
        status = str(response.status_code)

        api_requests_total.labels(method=method, path=path, status=status).inc()
        api_request_duration_seconds.labels(method=method, path=path).observe(duration)
        if response.status_code >= 400:
            error_code = response.headers.get("X-Error-Code", "unknown")
            api_errors_total.labels(method=method, path=path, error_code=error_code).inc()

        return response
