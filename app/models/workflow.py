"""Typed models for workflow execution (Milestone 6).

`ReviewFinding`/`EvidenceGap`/`ApprovalDecision` are the structured
building blocks a workflow stage produces. `WorkflowStageResult`/
`WorkflowExecution` are what `app.workflows.store.WorkflowStore`
actually persists between stages, so -- same reasoning `Citation`/
`RagAnswer` are pydantic while purely in-process types like
`RoutingDecision` stay dataclasses -- everything here is pydantic:
`model_dump(mode="json")` / `model_validate()` round-trips nested
citations/findings without hand-rolled reconstruction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.citation import Citation

VALID_FINDING_SEVERITIES = {"critical", "high", "medium", "low", "informational"}
VALID_FINDING_STATUSES = {"open", "accepted", "mitigated", "deferred", "not_applicable"}
VALID_APPROVAL_DECISIONS = {"approve", "reject", "request_changes", "cancel"}
VALID_STAGE_STATUSES = {
    "pending", "running", "completed", "failed", "skipped", "awaiting_approval",
}
VALID_EXECUTION_STATUSES = {
    "running", "awaiting_approval", "completed", "failed", "cancelled", "changes_requested",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReviewFinding(BaseModel):
    finding_id: str
    category: str
    title: str
    description: str
    severity: str
    recommendation: str | None = None
    blocking: bool = False
    source_advisors: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    status: str = "open"

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, value: str) -> str:
        if value not in VALID_FINDING_SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(VALID_FINDING_SEVERITIES)}, got '{value}'.")
        return value

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        if value not in VALID_FINDING_STATUSES:
            raise ValueError(f"status must be one of {sorted(VALID_FINDING_STATUSES)}, got '{value}'.")
        return value


class EvidenceGap(BaseModel):
    field: str
    description: str
    severity: str
    blocking: bool = False

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, value: str) -> str:
        if value not in VALID_FINDING_SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(VALID_FINDING_SEVERITIES)}, got '{value}'.")
        return value


class ApprovalDecision(BaseModel):
    decision: str
    reviewer: str | None = None
    comments: str | None = None
    decided_at: datetime = Field(default_factory=_utcnow)

    @field_validator("decision")
    @classmethod
    def _validate_decision(cls, value: str) -> str:
        if value not in VALID_APPROVAL_DECISIONS:
            raise ValueError(f"decision must be one of {sorted(VALID_APPROVAL_DECISIONS)}, got '{value}'.")
        return value


class WorkflowStageResult(BaseModel):
    stage_id: str
    stage_name: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    advisor_name: str | None = None
    answer: str | None = None
    structured_output: dict[str, Any] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        if value not in VALID_STAGE_STATUSES:
            raise ValueError(f"status must be one of {sorted(VALID_STAGE_STATUSES)}, got '{value}'.")
        return value


class WorkflowExecution(BaseModel):
    execution_id: str
    workflow_id: str
    workflow_version: str
    status: str
    current_stage: str | None = None
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    stage_results: list[WorkflowStageResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        if value not in VALID_EXECUTION_STATUSES:
            raise ValueError(f"status must be one of {sorted(VALID_EXECUTION_STATUSES)}, got '{value}'.")
        return value
