"""Application-service facade over Milestone 6's human-approval step.

`record_approval` is the only place that turns a reviewer's HTTP
request into an `ApprovalDecision` and calls `WorkflowEngine.approve` --
it enforces the one API-level rule the engine itself doesn't (a
`reject`/`request_changes` decision must carry a reviewer comment,
since an unexplained rejection gives the requester nothing to act on)
and proactively checks the execution is actually awaiting approval
before calling the engine, so a stale/duplicate decision gets a clear
`APPROVAL_ERROR` rather than the engine's generic
`WorkflowEngineError` message.
"""

from __future__ import annotations

from app.api.errors import ApiError, ErrorCode
from app.audit.logger import AuditContext, record_from_context
from app.models.workflow import ApprovalDecision, WorkflowExecution
from app.workflows.engine import WorkflowEngine

_COMMENT_REQUIRED_DECISIONS = {"reject", "request_changes"}


def list_pending_approvals(engine: WorkflowEngine) -> list[WorkflowExecution]:
    executions = [engine.store.load(execution_id) for execution_id in engine.store.list_execution_ids()]
    pending = [execution for execution in executions if execution.status == "awaiting_approval"]
    return sorted(pending, key=lambda execution: execution.started_at)


def record_approval(
    engine: WorkflowEngine, execution_id: str, decision: str, reviewer: str | None, comments: str | None,
    *, audit: AuditContext | None = None,
) -> WorkflowExecution:
    execution = engine.store.load(execution_id)
    if execution.status != "awaiting_approval":
        raise ApiError(
            409, ErrorCode.APPROVAL_ERROR,
            f"Execution '{execution_id}' is not awaiting approval (status='{execution.status}').",
        )
    if decision in _COMMENT_REQUIRED_DECISIONS and not (comments and comments.strip()):
        raise ApiError(
            400, ErrorCode.VALIDATION_ERROR,
            f"A comment is required when the decision is '{decision}'.",
        )

    result = engine.approve(execution_id, ApprovalDecision(decision=decision, reviewer=reviewer, comments=comments))
    record_from_context(
        audit, action="workflow_approval_decided", resource_type="workflow_execution", resource_id=execution_id,
        metadata={"decision": decision, "reviewer": reviewer, "status": result.status},
    )
    return result
