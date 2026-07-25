"""Request/response schemas for evaluation endpoints (Milestone 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from app.evaluation.run_models import VALID_EVALUATION_CATEGORIES, EvaluationRun


class RunEvaluationRequest(BaseModel):
    category: str = "rag"

    @field_validator("category")
    @classmethod
    def _validate_category(cls, value: str) -> str:
        if value not in VALID_EVALUATION_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(VALID_EVALUATION_CATEGORIES)}, got '{value}'.")
        return value


class EvaluationRunSummaryOut(BaseModel):
    run_id: str
    category: str
    started_at: datetime
    completed_at: datetime | None
    status: str
    total_cases: int
    passed_cases: int
    pass_rate: float
    organization_id: str | None = None  # multi-tenant boundary prep (Milestone 8) -- always None today


def build_evaluation_run_summary_out(run: EvaluationRun) -> EvaluationRunSummaryOut:
    return EvaluationRunSummaryOut(
        run_id=run.run_id, category=run.category, started_at=run.started_at, completed_at=run.completed_at,
        status=run.status, total_cases=run.total_cases, passed_cases=run.passed_cases, pass_rate=run.pass_rate,
        organization_id=run.organization_id,
    )


class EvaluationRunDetailOut(EvaluationRunSummaryOut):
    results: list[dict[str, Any]]
    summary: dict[str, Any]


def build_evaluation_run_detail_out(run: EvaluationRun) -> EvaluationRunDetailOut:
    return EvaluationRunDetailOut(
        **build_evaluation_run_summary_out(run).model_dump(), results=run.results, summary=run.summary,
    )
