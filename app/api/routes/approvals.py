"""Approval endpoints (Milestone 7).

Listing the pending-approval queue is viewer-level (visibility);
recording a decision (approve/reject/request_changes/cancel) is
reviewer-level -- the one permission that defines the "reviewer" role.
Workflow execution/resume/cancel live on the separate `workflows`
router; this router only ever records a human decision.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.dependencies.services import get_audit_store, get_workflow_engine
from app.api.schemas.approvals import ApprovalDecisionRequest, PendingApprovalOut, build_pending_approval_out
from app.api.schemas.workflows import ExecutionDetailOut, build_execution_detail_out
from app.api.services.approval_service import list_pending_approvals, record_approval
from app.api.services.workflow_service import collect_conflicts, collect_evidence_gaps, collect_findings
from app.audit.logger import AuditContext
from app.audit.store import AuditStore
from app.auth.dependencies import require_role
from app.auth.roles import Role
from app.auth.users import User
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
    user: User = Depends(require_role(Role.REVIEWER)),
) -> ExecutionDetailOut:
    request_id = getattr(request.state, "request_id", None)
    audit = AuditContext(store=audit_store, actor=user.username, role=user.role.value, request_id=request_id)
    reviewer = body.reviewer or user.username
    execution = record_approval(engine, execution_id, body.decision, reviewer, body.comments, audit=audit)
    return _detail_out(execution)
