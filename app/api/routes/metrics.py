"""Prometheus metrics endpoint (Milestone 8).

Mounted at the conventional `/metrics` path (not under `/api/v1`, and
unauthenticated) -- matching how Prometheus itself expects to scrape a
target. In a real deployment, restrict network access to this path at
the reverse proxy/network-policy layer (see `docs/operations/`), the
same way you would for any other unauthenticated metrics endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.responses import Response

from app.api.dependencies.services import get_workflow_engine
from app.api.services.workflow_service import list_executions
from app.telemetry.metrics import render_latest, workflows_awaiting_approval
from app.workflows.engine import WorkflowEngine

router = APIRouter()


@router.get("/metrics", summary="Prometheus metrics", tags=["Metrics"], include_in_schema=False)
def metrics_route(engine: WorkflowEngine = Depends(get_workflow_engine)) -> Response:
    # A small number of gauges reflect *current* state and are cheapest
    # to compute at scrape time rather than incrementally maintained --
    # avoids drift between "what the gauge says" and "what's actually
    # persisted."
    pending = sum(1 for execution in list_executions(engine) if execution.status == "awaiting_approval")
    workflows_awaiting_approval.set(pending)

    body, content_type = render_latest()
    return Response(content=body, media_type=content_type)
