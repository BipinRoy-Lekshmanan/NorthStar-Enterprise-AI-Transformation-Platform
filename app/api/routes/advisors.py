"""Advisor endpoints (Milestone 7).

Listing/detail/routing-preview are viewer-level ("view advisors" is
explicitly a viewer permission); directly querying a specific advisor
is engineer-level ("run advisor queries").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.dependencies.services import (
    get_audit_store,
    get_cost_tracker,
    get_ingestion_settings,
    get_privacy_settings,
    get_rag_service,
    get_router_settings,
)
from app.api.schemas.advisors import (
    AdvisorOut,
    AdvisorQueryRequest,
    RouteOnlyRequest,
    RouteOnlyResponse,
    build_advisor_out,
)
from app.api.schemas.query import QueryResponse, build_query_response
from app.api.services.advisor_service import get_advisor_detail, list_all_advisors, preview_routing
from app.api.services.knowledge_service import filter_restricted_citations, restricted_ids_for_role
from app.api.services.query_service import QueryFilters, ask_manual
from app.audit.logger import AuditContext
from app.audit.store import AuditStore
from app.auth.dependencies import require_role
from app.auth.roles import Role
from app.auth.users import User
from app.config.privacy import PrivacySettings, redact_citation_excerpts
from app.config.settings import IngestionSettings, RouterSettings
from app.rag.pipeline import RagService
from app.telemetry.cost_tracker import CostTracker

router = APIRouter()


@router.get("/advisors", summary="List available advisors", tags=["Advisors"], response_model=list[AdvisorOut])
def list_advisors_route(_user: User = Depends(require_role(Role.VIEWER))) -> list[AdvisorOut]:
    return [build_advisor_out(advisor) for advisor in list_all_advisors()]


@router.get(
    "/advisors/{advisor_id}", summary="Get advisor detail", tags=["Advisors"], response_model=AdvisorOut
)
def get_advisor_route(advisor_id: str, _user: User = Depends(require_role(Role.VIEWER))) -> AdvisorOut:
    return build_advisor_out(get_advisor_detail(advisor_id))


@router.post(
    "/advisors/{advisor_id}/query", summary="Query a specific advisor", tags=["Advisors"],
    response_model=QueryResponse,
)
def query_advisor_route(
    advisor_id: str,
    request: Request,
    body: AdvisorQueryRequest,
    service: RagService = Depends(get_rag_service),
    ingestion_settings: IngestionSettings = Depends(get_ingestion_settings),
    audit_store: AuditStore = Depends(get_audit_store),
    cost_tracker: CostTracker = Depends(get_cost_tracker),
    privacy_settings: PrivacySettings = Depends(get_privacy_settings),
    user: User = Depends(require_role(Role.ENGINEER)),
) -> QueryResponse:
    filters = QueryFilters(document_id=body.document_id, source_file=body.source_file)
    request_id = getattr(request.state, "request_id", None)
    audit = AuditContext(store=audit_store, actor=user.username, role=user.role.value, request_id=request_id)

    result = ask_manual(
        service, body.question, advisor_id, filters,
        include_diagnostics=body.include_diagnostics, include_context=body.include_retrieved_context, audit=audit,
        cost_tracker=cost_tracker, actor=user.username,
    )
    response = build_query_response(result, request_id)
    restricted_ids = restricted_ids_for_role(user.role, ingestion_settings)
    response.citations = filter_restricted_citations(response.citations, restricted_ids)
    response.citations = redact_citation_excerpts(response.citations, privacy_settings.include_citation_excerpts)
    return response


@router.post(
    "/advisors/route", summary="Preview routing without executing any advisor", tags=["Advisors"],
    response_model=RouteOnlyResponse,
)
def route_only_route(
    body: RouteOnlyRequest,
    service: RagService = Depends(get_rag_service),
    router_settings: RouterSettings = Depends(get_router_settings),
    _user: User = Depends(require_role(Role.VIEWER)),
) -> RouteOnlyResponse:
    decision = preview_routing(service, router_settings, body.question)
    return RouteOnlyResponse(
        primary_advisor=decision.primary_advisor,
        supporting_advisors=decision.supporting_advisors,
        confidence=decision.confidence,
        rationale=decision.rationale,
        detected_domains=decision.detected_domains,
        fallback_used=decision.fallback_used,
    )
