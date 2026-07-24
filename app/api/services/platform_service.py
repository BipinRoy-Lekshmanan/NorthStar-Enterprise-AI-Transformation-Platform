"""Application-service facade for operational diagnostics (Milestone 7).

`get_health_detail` performs one cheap, real retrieval call (rather
than reaching into `Retriever`'s private vector-store attribute) to
verify the grounded pipeline actually answers, mirroring how a
production health check exercises a dependency instead of just
checking that an object reference exists. `list_recent_audit_events`
is a direct pass-through to `AuditStore.list_events` -- no new logic.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.agents.registry import list_advisors
from app.api.version import APP_VERSION
from app.audit.models import AuditEvent
from app.audit.store import AuditStore
from app.models.query import RetrievalQuery
from app.rag.pipeline import RagService
from app.workflows.registry import list_workflows

_HEALTH_CHECK_QUERY = "platform health check"


def get_health_detail(service: RagService, started_at: datetime) -> dict:
    components: dict[str, str] = {}
    try:
        service.retriever.retrieve(RetrievalQuery(text=_HEALTH_CHECK_QUERY, top_k=1))
        components["retrieval_pipeline"] = "ok"
    except Exception as exc:  # noqa: BLE001 -- a health check must never propagate the underlying error
        components["retrieval_pipeline"] = f"error: {exc}"

    status = "ok" if all(value == "ok" for value in components.values()) else "degraded"
    uptime_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()

    return {
        "status": status,
        "version": APP_VERSION,
        "uptime_seconds": uptime_seconds,
        "components": components,
        "advisor_count": len(list_advisors()),
        "workflow_count": len(list_workflows()),
    }


def list_recent_audit_events(store: AuditStore, limit: int = 50) -> list[AuditEvent]:
    return store.list_events(limit=limit)
