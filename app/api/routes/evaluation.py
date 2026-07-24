"""Evaluation endpoints (Milestone 7).

Triggering a run is engineer-level (a QA/diagnostic action over the
existing pipeline, not a persisted knowledge-base mutation -- distinct
from the administrator-tier ingest/index/rebuild on the knowledge
router). Viewing run history is viewer-level.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies.services import (
    get_audit_store,
    get_evaluation_run_store,
    get_rag_service,
    get_workflow_engine,
)
from app.api.schemas.common import DEFAULT_PAGE_SIZE, PaginatedResponse, paginate_slice, validate_pagination
from app.api.schemas.evaluation import (
    EvaluationRunDetailOut,
    EvaluationRunSummaryOut,
    RunEvaluationRequest,
    build_evaluation_run_detail_out,
    build_evaluation_run_summary_out,
)
from app.api.services.evaluation_service import get_run, list_runs, run_and_save_evaluation
from app.audit.logger import AuditContext
from app.audit.store import AuditStore
from app.auth.dependencies import require_role
from app.auth.roles import Role
from app.auth.users import User
from app.evaluation.run_store import EvaluationRunStore
from app.rag.pipeline import RagService
from app.workflows.engine import WorkflowEngine

router = APIRouter()


@router.post(
    "/evaluation/runs", summary="Run an evaluation dataset and persist the result", tags=["Evaluation"],
    response_model=EvaluationRunDetailOut,
)
def run_evaluation_route(
    body: RunEvaluationRequest,
    request: Request,
    store: EvaluationRunStore = Depends(get_evaluation_run_store),
    service: RagService = Depends(get_rag_service),
    engine: WorkflowEngine = Depends(get_workflow_engine),
    audit_store: AuditStore = Depends(get_audit_store),
    user: User = Depends(require_role(Role.ENGINEER)),
) -> EvaluationRunDetailOut:
    request_id = getattr(request.state, "request_id", None)
    audit = AuditContext(store=audit_store, actor=user.username, role=user.role.value, request_id=request_id)
    run = run_and_save_evaluation(store, body.category, service=service, engine=engine, audit=audit)
    return build_evaluation_run_detail_out(run)


@router.get(
    "/evaluation/runs", summary="List past evaluation runs", tags=["Evaluation"],
    response_model=PaginatedResponse[EvaluationRunSummaryOut],
)
def list_evaluation_runs_route(
    category: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
    store: EvaluationRunStore = Depends(get_evaluation_run_store),
    _user: User = Depends(require_role(Role.VIEWER)),
) -> PaginatedResponse[EvaluationRunSummaryOut]:
    page, page_size = validate_pagination(page, page_size)
    runs = list_runs(store, category)
    page_items, total_items, total_pages = paginate_slice(runs, page, page_size)
    return PaginatedResponse[EvaluationRunSummaryOut](
        items=[build_evaluation_run_summary_out(run) for run in page_items],
        page=page, page_size=page_size, total_items=total_items, total_pages=total_pages,
    )


@router.get(
    "/evaluation/runs/{run_id}", summary="Get a past evaluation run's full detail", tags=["Evaluation"],
    response_model=EvaluationRunDetailOut,
)
def get_evaluation_run_route(
    run_id: str, store: EvaluationRunStore = Depends(get_evaluation_run_store),
    _user: User = Depends(require_role(Role.VIEWER)),
) -> EvaluationRunDetailOut:
    return build_evaluation_run_detail_out(get_run(store, run_id))
