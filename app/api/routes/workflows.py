"""Workflow endpoints (Milestone 7).

Listing/describing/viewing executions and reports are viewer-level;
executing/resuming/cancelling a workflow are engineer-level (mirrors
"run advisor queries" being engineer-tier for `/advisors/{id}/query`).
Approval decisions (approve/reject/request_changes) are handled by a
separate `approvals` router -- reviewer-tier -- not here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api.dependencies.services import get_audit_store, get_idempotency_store, get_lock_registry, get_workflow_engine
from app.api.errors import ApiError, ErrorCode
from app.api.schemas.common import DEFAULT_PAGE_SIZE, PaginatedResponse, paginate_slice, validate_pagination
from app.api.schemas.workflows import (
    ExecuteWorkflowRequest,
    ExecutionDetailOut,
    ExecutionSummaryOut,
    WorkflowDetailOut,
    WorkflowExampleOut,
    WorkflowReportOut,
    WorkflowSummaryOut,
    build_execution_detail_out,
    build_execution_summary_out,
    build_workflow_detail_out,
    build_workflow_example_out,
    build_workflow_summary_out,
)
from app.api.services.idempotency_service import check_idempotency, save_idempotent_response
from app.api.services.workflow_service import (
    cancel_execution,
    collect_conflicts,
    collect_evidence_gaps,
    collect_findings,
    execute_workflow,
    get_execution,
    get_report,
    get_workflow_detail,
    list_all_workflows,
    list_executions,
    list_workflow_examples,
    resume_execution,
)
from app.audit.logger import AuditContext
from app.audit.store import AuditStore
from app.auth.dependencies import require_role
from app.auth.roles import Role
from app.auth.users import User
from app.export.common import build_workflow_report_export_envelope
from app.export.markdown_renderer import render_workflow_report_markdown
from app.resilience.concurrency import LockRegistry
from app.resilience.idempotency import IdempotencyStore
from app.workflows.engine import WorkflowEngine
from app.workflows.synthesis import dedupe_citations

router = APIRouter()


def _detail_out(execution) -> ExecutionDetailOut:
    return build_execution_detail_out(
        execution,
        findings=collect_findings(execution),
        evidence_gaps=collect_evidence_gaps(execution),
        conflicts=collect_conflicts(execution),
        citations=dedupe_citations(execution.stage_results),
    )


@router.get("/workflows", summary="List available workflows", tags=["Workflows"], response_model=list[WorkflowSummaryOut])
def list_workflows_route(_user: User = Depends(require_role(Role.VIEWER))) -> list[WorkflowSummaryOut]:
    return [build_workflow_summary_out(definition) for definition in list_all_workflows()]


# NOTE: registered before `/workflows/{workflow_id}` -- Starlette matches
# routes in registration order, so this literal-segment route must come
# first or `/workflows/executions` would be swallowed by the
# single-path-param route below (as `workflow_id="executions"`).
@router.get(
    "/workflows/executions", summary="List workflow executions", tags=["Workflows"],
    response_model=PaginatedResponse[ExecutionSummaryOut],
)
def list_executions_route(
    workflow_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
    engine: WorkflowEngine = Depends(get_workflow_engine),
    _user: User = Depends(require_role(Role.VIEWER)),
) -> PaginatedResponse[ExecutionSummaryOut]:
    page, page_size = validate_pagination(page, page_size)
    executions = list_executions(engine, workflow_id)
    page_items, total_items, total_pages = paginate_slice(executions, page, page_size)
    return PaginatedResponse[ExecutionSummaryOut](
        items=[build_execution_summary_out(execution) for execution in page_items],
        page=page, page_size=page_size, total_items=total_items, total_pages=total_pages,
    )


@router.get(
    "/workflows/{workflow_id}", summary="Describe a workflow's stages and input schema", tags=["Workflows"],
    response_model=WorkflowDetailOut,
)
def get_workflow_route(workflow_id: str, _user: User = Depends(require_role(Role.VIEWER))) -> WorkflowDetailOut:
    return build_workflow_detail_out(get_workflow_detail(workflow_id))


@router.get(
    "/workflows/{workflow_id}/examples", summary="List example input payloads for a workflow", tags=["Workflows"],
    response_model=list[WorkflowExampleOut],
)
def list_workflow_examples_route(
    workflow_id: str, _user: User = Depends(require_role(Role.VIEWER)),
) -> list[WorkflowExampleOut]:
    get_workflow_detail(workflow_id)  # raises UnknownWorkflowError -> 404 for a bad id
    return [build_workflow_example_out(example) for example in list_workflow_examples(workflow_id)]


@router.post(
    "/workflows/{workflow_id}/execute", summary="Execute a workflow", tags=["Workflows"],
    response_model=ExecutionDetailOut,
)
def execute_workflow_route(
    workflow_id: str,
    body: ExecuteWorkflowRequest,
    request: Request,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    audit_store: AuditStore = Depends(get_audit_store),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    user: User = Depends(require_role(Role.ENGINEER)),
) -> ExecutionDetailOut:
    idempotency_endpoint = f"workflow_execute:{workflow_id}"
    request_body = body.model_dump(mode="json")
    cached = check_idempotency(request, idempotency_store, idempotency_endpoint, request_body)
    if cached is not None:
        return JSONResponse(status_code=cached.status_code, content=cached.body)

    request_id = getattr(request.state, "request_id", None)
    audit = AuditContext(store=audit_store, actor=user.username, role=user.role.value, request_id=request_id)
    execution = execute_workflow(engine, workflow_id, body.inputs, audit=audit)
    result = _detail_out(execution)
    save_idempotent_response(
        request, idempotency_store, idempotency_endpoint, request_body, 200, result.model_dump(mode="json"),
    )
    return result


@router.get(
    "/workflows/executions/{execution_id}", summary="Get a workflow execution's full detail", tags=["Workflows"],
    response_model=ExecutionDetailOut,
)
def get_execution_route(
    execution_id: str, engine: WorkflowEngine = Depends(get_workflow_engine),
    _user: User = Depends(require_role(Role.VIEWER)),
) -> ExecutionDetailOut:
    return _detail_out(get_execution(engine, execution_id))


@router.post(
    "/workflows/executions/{execution_id}/resume", summary="Resume a running execution", tags=["Workflows"],
    response_model=ExecutionDetailOut,
)
def resume_execution_route(
    execution_id: str,
    request: Request,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    audit_store: AuditStore = Depends(get_audit_store),
    lock_registry: LockRegistry = Depends(get_lock_registry),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    user: User = Depends(require_role(Role.ENGINEER)),
) -> ExecutionDetailOut:
    idempotency_endpoint = f"workflow_resume:{execution_id}"
    cached = check_idempotency(request, idempotency_store, idempotency_endpoint, {})
    if cached is not None:
        return JSONResponse(status_code=cached.status_code, content=cached.body)

    request_id = getattr(request.state, "request_id", None)
    audit = AuditContext(store=audit_store, actor=user.username, role=user.role.value, request_id=request_id)
    execution = resume_execution(engine, execution_id, audit=audit, lock_registry=lock_registry)
    result = _detail_out(execution)
    save_idempotent_response(request, idempotency_store, idempotency_endpoint, {}, 200, result.model_dump(mode="json"))
    return result


@router.post(
    "/workflows/executions/{execution_id}/cancel", summary="Cancel an execution", tags=["Workflows"],
    response_model=ExecutionDetailOut,
)
def cancel_execution_route(
    execution_id: str,
    request: Request,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    audit_store: AuditStore = Depends(get_audit_store),
    lock_registry: LockRegistry = Depends(get_lock_registry),
    user: User = Depends(require_role(Role.ENGINEER)),
) -> ExecutionDetailOut:
    request_id = getattr(request.state, "request_id", None)
    audit = AuditContext(store=audit_store, actor=user.username, role=user.role.value, request_id=request_id)
    execution = cancel_execution(engine, execution_id, audit=audit, lock_registry=lock_registry)
    return _detail_out(execution)


@router.get(
    "/workflows/executions/{execution_id}/report", summary="Get a completed execution's final report",
    tags=["Workflows"], response_model=WorkflowReportOut,
)
def get_report_route(
    execution_id: str,
    format: str = Query(default="json", pattern="^(json|markdown)$", description="'json' (default) or 'markdown'"),
    engine: WorkflowEngine = Depends(get_workflow_engine),
    _user: User = Depends(require_role(Role.VIEWER)),
) -> WorkflowReportOut:
    execution = get_execution(engine, execution_id)
    sections = get_report(execution)
    if sections is None:
        raise ApiError(
            404, ErrorCode.NOT_FOUND,
            f"Execution '{execution_id}' has not yet produced a final report (status='{execution.status}').",
        )
    report = WorkflowReportOut(
        execution_id=execution.execution_id, workflow_id=execution.workflow_id, status=execution.status,
        sections=sections,
    )
    if format == "markdown":
        envelope = build_workflow_report_export_envelope(
            report.model_dump(mode="json"), _detail_out(execution).model_dump(mode="json"),
        )
        return PlainTextResponse(render_workflow_report_markdown(envelope), media_type="text/markdown")
    return report
