"""Request/response schemas for approval endpoints (Milestone 7)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator

from app.models.workflow import VALID_APPROVAL_DECISIONS, WorkflowExecution


class ApprovalDecisionRequest(BaseModel):
    decision: str
    reviewer: str | None = None
    comments: str | None = None

    @field_validator("decision")
    @classmethod
    def _validate_decision(cls, value: str) -> str:
        if value not in VALID_APPROVAL_DECISIONS:
            raise ValueError(f"decision must be one of {sorted(VALID_APPROVAL_DECISIONS)}, got '{value}'.")
        return value


class PendingApprovalOut(BaseModel):
    execution_id: str
    workflow_id: str
    workflow_version: str
    current_stage: str | None
    started_at: datetime
    findings_count: int
    evidence_gaps_count: int


def build_pending_approval_out(execution: WorkflowExecution) -> PendingApprovalOut:
    findings_count = sum(len(result.structured_output.get("findings", [])) for result in execution.stage_results)
    evidence_gaps_count = sum(
        len(result.structured_output.get("evidence_gaps", [])) for result in execution.stage_results
    )
    return PendingApprovalOut(
        execution_id=execution.execution_id, workflow_id=execution.workflow_id,
        workflow_version=execution.workflow_version, current_stage=execution.current_stage,
        started_at=execution.started_at, findings_count=findings_count, evidence_gaps_count=evidence_gaps_count,
    )
