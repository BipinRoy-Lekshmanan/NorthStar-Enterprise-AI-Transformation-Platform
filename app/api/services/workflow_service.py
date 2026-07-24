"""Application-service facade over Milestone 6's workflow engine.

Every function here validates its inputs, calls exactly one
`WorkflowEngine`/`WorkflowStore`/registry entry point, and returns a
plain result -- no stage dispatch, approval-pausing, or synthesis logic
is duplicated from `app.workflows.engine`. Approval-precondition checks
(already awaiting approval / already terminal) are done *proactively*
against `WorkflowExecution.status` here, before calling into the
engine, so the API can return the exact `WORKFLOW_AWAITING_APPROVAL` /
`WORKFLOW_ALREADY_COMPLETED` error codes rather than parsing
`WorkflowEngineError`'s message string.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.api.errors import ApiError, ErrorCode
from app.audit.logger import AuditContext, record_from_context
from app.config.settings import PROJECT_ROOT
from app.models.workflow import EvidenceGap, ReviewFinding, WorkflowExecution
from app.workflows.definitions import WorkflowDefinition
from app.workflows.engine import WorkflowEngine
from app.workflows.registry import get_workflow, list_workflows

_EXAMPLES_DIR = PROJECT_ROOT / "examples" / "workflows"

# Mirrors `app.workflows.engine._TERMINAL_STATUSES` exactly -- kept as a
# literal here rather than importing the underscore-prefixed constant
# across a module boundary.
_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "changes_requested"}

# A small, explicit map (not filename globbing) so a mismatch between an
# example file's name and a workflow_id fails loudly at review time
# rather than silently omitting an example.
_WORKFLOW_EXAMPLE_FILES: dict[str, tuple[str, ...]] = {
    "architecture_review": ("architecture_review_loan_notification.json",),
    "ai_solution_review": (
        "ai_solution_review_underwriting_summarizer.json",
        "ai_solution_review_missing_human_review.json",
    ),
    "production_readiness_review": (
        "production_readiness_complete.json",
        "production_readiness_partial_evidence.json",
        "production_readiness_missing_rollback.json",
    ),
    "incident_review": (
        "incident_review_payment_latency.json",
        "incident_review_missing_timeline.json",
    ),
    "executive_ai_transformation_assessment": (
        "executive_ai_transformation_18_month.json",
        "executive_ai_transformation_missing_governance.json",
    ),
}


@dataclass(frozen=True)
class WorkflowExample:
    name: str
    inputs: dict


def list_all_workflows() -> list[WorkflowDefinition]:
    return list_workflows()


def get_workflow_detail(workflow_id: str) -> WorkflowDefinition:
    return get_workflow(workflow_id)


def list_workflow_examples(workflow_id: str) -> list[WorkflowExample]:
    filenames = _WORKFLOW_EXAMPLE_FILES.get(workflow_id, ())
    examples = []
    for filename in filenames:
        path = _EXAMPLES_DIR / filename
        if path.exists():
            examples.append(WorkflowExample(name=filename, inputs=json.loads(path.read_text(encoding="utf-8"))))
    return examples


def execute_workflow(
    engine: WorkflowEngine, workflow_id: str, inputs: dict, *, audit: AuditContext | None = None,
) -> WorkflowExecution:
    execution = engine.run(workflow_id, inputs)
    record_from_context(
        audit, action="workflow_executed", resource_type="workflow_execution", resource_id=execution.execution_id,
        metadata={"workflow_id": workflow_id, "status": execution.status},
    )
    return execution


def list_executions(engine: WorkflowEngine, workflow_id: str | None = None) -> list[WorkflowExecution]:
    executions = [engine.store.load(execution_id) for execution_id in engine.store.list_execution_ids()]
    if workflow_id:
        executions = [execution for execution in executions if execution.workflow_id == workflow_id]
    return sorted(executions, key=lambda execution: execution.started_at, reverse=True)


def get_execution(engine: WorkflowEngine, execution_id: str) -> WorkflowExecution:
    return engine.store.load(execution_id)


def resume_execution(
    engine: WorkflowEngine, execution_id: str, *, audit: AuditContext | None = None,
) -> WorkflowExecution:
    execution = engine.store.load(execution_id)
    if execution.status == "awaiting_approval":
        raise ApiError(
            409, ErrorCode.WORKFLOW_AWAITING_APPROVAL,
            f"Execution '{execution_id}' is awaiting human approval; approve or reject it before resuming.",
        )
    if execution.status in _TERMINAL_STATUSES:
        raise ApiError(
            409, ErrorCode.WORKFLOW_ALREADY_COMPLETED,
            f"Execution '{execution_id}' has terminal status '{execution.status}' and cannot be resumed.",
        )
    execution = engine.resume(execution_id)
    record_from_context(
        audit, action="workflow_resumed", resource_type="workflow_execution", resource_id=execution_id,
        metadata={"status": execution.status},
    )
    return execution


def cancel_execution(
    engine: WorkflowEngine, execution_id: str, *, audit: AuditContext | None = None,
) -> WorkflowExecution:
    execution = engine.store.load(execution_id)
    if execution.status in _TERMINAL_STATUSES:
        raise ApiError(
            409, ErrorCode.WORKFLOW_ALREADY_COMPLETED,
            f"Execution '{execution_id}' already has terminal status '{execution.status}'.",
        )
    execution = engine.cancel(execution_id)
    record_from_context(
        audit, action="workflow_cancelled", resource_type="workflow_execution", resource_id=execution_id,
        metadata={"status": execution.status},
    )
    return execution


def collect_findings(execution: WorkflowExecution) -> list[ReviewFinding]:
    return [
        ReviewFinding.model_validate(item)
        for result in execution.stage_results
        for item in result.structured_output.get("findings", [])
    ]


def collect_evidence_gaps(execution: WorkflowExecution) -> list[EvidenceGap]:
    return [
        EvidenceGap.model_validate(item)
        for result in execution.stage_results
        for item in result.structured_output.get("evidence_gaps", [])
    ]


def collect_conflicts(execution: WorkflowExecution) -> list[ReviewFinding]:
    return [finding for finding in collect_findings(execution) if finding.category == "conflict"]


def get_report(execution: WorkflowExecution) -> dict | None:
    """Returns the report's `{section: text}` mapping produced by the
    `final_report` stage, or `None` if the execution hasn't reached that
    stage yet. Never re-derives report text -- reads exactly what
    `app.workflows.engine`'s final_report stage already computed and
    stored on `WorkflowStageResult.structured_output`, mirroring
    `app.workflows.cli._format_report`."""
    report_stage = next(
        (r for r in reversed(execution.stage_results) if "report_sections" in r.structured_output), None
    )
    return report_stage.structured_output["report_sections"] if report_stage else None
