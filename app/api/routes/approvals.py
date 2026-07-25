"""Approval endpoints (Milestone 7).

Listing the pending-approval queue is viewer-level (visibility);
recording a decision (approve/reject/request_changes/cancel) is
reviewer-level -- the one permission that defines the "reviewer" role.
Workflow execution/resume/cancel live on the separate `workflows`
router; this router only ever records a human decision.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.dependencies.services import get_audit_store, get_idempotency_store, get_lock_registry, get_workflow_engine
from app.api.schemas.approvals import ApprovalDecisionRequest, PendingApprovalOut, build_pending_approval_out
from app.api.schemas.workflows import ExecutionDetailOut, build_execution_detail_out
from app.api.services.approval_service import list_pending_approvals, record_approval
from app.api.services.idempotency_service import check_idempotency, save_idempotent_response
from app.api.services.workflow_service import collect_conflicts, collect_evidence_gaps, collect_findings
from app.audit.logger import AuditContext
from app.audit.store import AuditStore
from app.auth.dependencies import require_role
from app.auth.roles import Role
from app.auth.users import User
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


@router.get(
    "/approvals", summary="List executions awaiting human approval", tags=["Approvals"],
    response_model=list[PendingApprovalOut],
)
def list_pending_approvals_route(
    engine: WorkflowEngine = Depends(get_workflow_engine), _user: User = Depends(require_role(Role.VIEWER)),
) -> list[PendingApprovalOut]:
    return [build_pending_approval_out(execution) for execution in list_pending_approvals(engine)]


@router.post(
    "/approvals/{execution_id}/decide", summary="Record an approval decision", tags=["Approvals"],
    response_model=ExecutionDetailOut,
)
def decide_approval_route(
    execution_id: str,
    body: ApprovalDecisionRequest,
    request: Request,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    audit_store: AuditStore = Depends(get_audit_store),
    lock_registry: LockRegistry = Depends(get_lock_registry),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    user: User = Depends(require_role(Role.REVIEWER)),
) -> ExecutionDetailOut:
    idempotency_endpoint = f"approval_decide:{execution_id}"
    request_body = body.model_dump(mode="json")
    cached = check_idempotency(request, idempotency_store, idempotency_endpoint, request_body)
    if cached is not None:
        return JSONResponse(status_code=cached.status_code, content=cached.body)

    request_id = getattr(request.state, "request_id", None)
    audit = AuditContext(store=audit_store, actor=user.username, role=user.role.value, request_id=request_id)
    reviewer = body.reviewer or user.username
    execution = record_approval(
        engine, execution_id, body.decision, reviewer, body.comments, audit=audit, lock_registry=lock_registry,
    )
    result = _detail_out(execution)
    save_idempotent_response(
        request, idempotency_store, idempotency_endpoint, request_body, 200, result.model_dump(mode="json"),
    )
    return result
