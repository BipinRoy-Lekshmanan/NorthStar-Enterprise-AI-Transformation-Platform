"""Typed model for persisted evaluation run history (Milestone 7).

Neither `app.evaluation.rag_evaluator` nor `app.evaluation.workflow_evaluator`
persisted anything before this milestone -- both only printed a report to
stdout. `EvaluationRun` wraps whichever evaluator ran with a stable,
category-agnostic envelope (`results`/`summary` stay plain `dict`s
rather than a union of the two evaluators' distinct result dataclasses)
so `EvaluationRunStore` can save/load either category through one
model, the same reasoning `WorkflowExecution` is pydantic so
`model_dump(mode="json")`/`model_validate()` round-trip without
hand-rolled reconstruction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

VALID_EVALUATION_CATEGORIES = {"rag", "workflows"}
VALID_EVALUATION_RUN_STATUSES = {"completed", "failed"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EvaluationRun(BaseModel):
    run_id: str
    category: str
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None
    status: str = "completed"
    total_cases: int = 0
    passed_cases: int = 0
    results: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    # Multi-tenant boundary prep (Milestone 8): always None today -- this
    # platform has exactly one tenant, and nothing filters or scopes runs
    # by this field. It exists so a future multi-tenant milestone can
    # start populating and querying by it without another schema change.
    organization_id: str | None = None

    @field_validator("category")
    @classmethod
    def _validate_category(cls, value: str) -> str:
        if value not in VALID_EVALUATION_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(VALID_EVALUATION_CATEGORIES)}, got '{value}'.")
        return value

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        if value not in VALID_EVALUATION_RUN_STATUSES:
            raise ValueError(f"status must be one of {sorted(VALID_EVALUATION_RUN_STATUSES)}, got '{value}'.")
        return value

    @property
    def pass_rate(self) -> float:
        return (self.passed_cases / self.total_cases) if self.total_cases else 0.0
