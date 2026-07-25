"""Grounded query endpoint (Milestone 7).

`POST /query` is a viewer-level capability ("ask grounded questions" is
explicitly a viewer permission) supporting both manual advisor selection
and automatic routing through the same request shape. A dedicated,
engineer-level `POST /advisors/{advisor_id}/query` is added separately
(see `app.api.routes.advisors`) for the distinct "run advisor queries"
permission.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse

from app.api.dependencies.services import (
    get_audit_store,
    get_cost_tracker,
    get_ingestion_settings,
    get_rag_service,
    get_rag_settings,
    get_router_settings,
)
from app.api.schemas.query import QueryRequest, QueryResponse, build_query_response
from app.api.services.knowledge_service import filter_restricted_citations, restricted_ids_for_role
from app.api.services.query_service import QueryFilters, ask_auto, ask_manual
from app.audit.logger import AuditContext
from app.audit.store import AuditStore
from app.auth.dependencies import require_role
from app.auth.roles import Role
from app.auth.users import User
from app.config.settings import IngestionSettings, RagSettings, RouterSettings
from app.export.common import build_query_export_envelope
from app.export.markdown_renderer import render_query_answer_markdown
from app.rag.pipeline import RagService
from app.telemetry.cost_tracker import CostTracker

router = APIRouter()


@router.post(
    "/query", summary="Ask a grounded question", tags=["Queries"], response_model=QueryResponse,
)
def ask_question(
    request: Request,
    body: QueryRequest,
    format: str = Query(default="json", pattern="^(json|markdown)$", description="'json' (default) or 'markdown'"),
    service: RagService = Depends(get_rag_service),
    rag_settings: RagSettings = Depends(get_rag_settings),
    router_settings: RouterSettings = Depends(get_router_settings),
    ingestion_settings: IngestionSettings = Depends(get_ingestion_settings),
    audit_store: AuditStore = Depends(get_audit_store),
    cost_tracker: CostTracker = Depends(get_cost_tracker),
    user: User = Depends(require_role(Role.VIEWER)),
) -> QueryResponse:
    filters = QueryFilters(
        document_id=body.filters.document_ids[0] if body.filters.document_ids else None,
        source_file=body.filters.source_files[0] if body.filters.source_files else None,
    )
    request_id = getattr(request.state, "request_id", None)
    audit = AuditContext(store=audit_store, actor=user.username, role=user.role.value, request_id=request_id)

    if body.advisor == "auto":
        result = ask_auto(
            service, rag_settings, router_settings, body.question, filters,
            max_supporting_advisors=body.max_supporting_advisors,
            include_diagnostics=body.include_diagnostics,
            include_context=body.include_retrieved_context,
            audit=audit, cost_tracker=cost_tracker, actor=user.username,
        )
    else:
        result = ask_manual(
            service, body.question, body.advisor, filters,
            include_diagnostics=body.include_diagnostics,
            include_context=body.include_retrieved_context,
            audit=audit, cost_tracker=cost_tracker, actor=user.username,
        )

    response = build_query_response(result, request_id)
    restricted_ids = restricted_ids_for_role(user.role, ingestion_settings)
    response.citations = filter_restricted_citations(response.citations, restricted_ids)
    if format == "markdown":
        markdown_text = render_query_answer_markdown(build_query_export_envelope(response.model_dump(mode="json")))
        return PlainTextResponse(markdown_text, media_type="text/markdown")
    return response
