"""Platform operations endpoints (Milestone 7).

Detailed health/diagnostics is viewer-level (visibility into whether
the platform is working). The audit log view is administrator-level --
it can surface who did what across every user, so it's restricted to
the same role that already runs knowledge-base administration.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.dependencies.services import get_audit_store, get_cost_tracker, get_rag_service, get_started_at
from app.api.schemas.platform import (
    AuditEventOut,
    HealthDetailOut,
    PlatformInfoOut,
    UsageSummaryOut,
    build_audit_event_out,
)
from app.api.services.platform_service import (
    get_health_detail,
    get_platform_info,
    get_usage_summary,
    list_recent_audit_events,
)
from app.audit.store import AuditStore
from app.auth.dependencies import require_role
from app.auth.roles import Role
from app.auth.users import User
from app.rag.pipeline import RagService
from app.telemetry.cost_tracker import CostTracker

router = APIRouter()


@router.get(
    "/platform/health", summary="Detailed platform health and component diagnostics", tags=["Platform"],
    response_model=HealthDetailOut,
)
def health_detail_route(
    service: RagService = Depends(get_rag_service),
    started_at=Depends(get_started_at),
    _user: User = Depends(require_role(Role.VIEWER)),
) -> HealthDetailOut:
    return HealthDetailOut(**get_health_detail(service, started_at))


@router.get(
    "/platform/info", summary="Platform version/build/schema/prompt info", tags=["Platform"],
    response_model=PlatformInfoOut,
)
def platform_info_route(_user: User = Depends(require_role(Role.VIEWER))) -> PlatformInfoOut:
    return PlatformInfoOut(**get_platform_info())


@router.get(
    "/platform/usage", summary="Today's usage cost and budget status", tags=["Platform"],
    response_model=UsageSummaryOut,
)
def usage_summary_route(
    cost_tracker: CostTracker = Depends(get_cost_tracker), _user: User = Depends(require_role(Role.VIEWER)),
) -> UsageSummaryOut:
    return UsageSummaryOut(**get_usage_summary(cost_tracker))


@router.get(
    "/platform/audit", summary="Recent audit events", tags=["Platform"], response_model=list[AuditEventOut],
)
def audit_events_route(
    limit: int = Query(default=50, ge=1, le=500),
    store: AuditStore = Depends(get_audit_store),
    _user: User = Depends(require_role(Role.ADMINISTRATOR)),
) -> list[AuditEventOut]:
    return [build_audit_event_out(event) for event in list_recent_audit_events(store, limit)]
