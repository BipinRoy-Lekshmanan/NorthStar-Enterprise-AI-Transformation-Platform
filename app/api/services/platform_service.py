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
from app.config.environment import current_environment
from app.config.prompt_config import PROMPT_VERSION
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


def _schema_head_revision() -> str | None:
    """The Alembic revision id this codebase's migrations expect the
    database to be at (`app/db/migrations`'s HEAD) -- a static fact
    about the code, not a live query against the running database (that
    distinction is `python -m app.db current`'s job). Returns `None`
    rather than raising if Alembic's own files can't be read, since
    `/platform/info` should never fail just because this one extra
    fact is unavailable."""
    try:
        from alembic.script import ScriptDirectory

        from app.db.cli import alembic_config

        return ScriptDirectory.from_config(alembic_config()).get_current_head()
    except Exception:  # noqa: BLE001 -- best-effort diagnostic, never fatal
        return None


def get_platform_info() -> dict:
    return {
        "version": APP_VERSION,
        "environment": current_environment().value,
        "prompt_version": PROMPT_VERSION,
        "schema_version": _schema_head_revision(),
    }


def get_readiness(service: RagService, audit_store: AuditStore) -> dict:
    """Real dependency checks for a Kubernetes-style readiness probe --
    deliberately lighter than `get_health_detail`'s viewer-authenticated
    diagnostics (a probe can't send credentials), just enough to decide
    ready vs. not-ready."""
    checks: dict[str, str] = {}
    try:
        service.retriever.retrieve(RetrievalQuery(text=_HEALTH_CHECK_QUERY, top_k=1))
        checks["retrieval_pipeline"] = "ok"
    except Exception as exc:  # noqa: BLE001 -- a readiness check must never propagate the underlying error
        checks["retrieval_pipeline"] = f"error: {exc}"

    try:
        audit_store.list_events(limit=1)
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc}"

    return {"ready": all(value == "ok" for value in checks.values()), "checks": checks}
