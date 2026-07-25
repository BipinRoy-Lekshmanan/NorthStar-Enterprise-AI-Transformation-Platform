"""Request/response schemas for the background operations API (Milestone 8)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.operations.background import OperationSummary


class OperationOut(BaseModel):
    operation_id: str
    operation_type: str
    status: str
    created_by: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result: dict[str, Any] | None
    error_message: str | None


def build_operation_out(summary: OperationSummary) -> OperationOut:
    return OperationOut(
        operation_id=summary.operation_id, operation_type=summary.operation_type, status=summary.status,
        created_by=summary.created_by, created_at=summary.created_at, started_at=summary.started_at,
        completed_at=summary.completed_at, result=summary.result, error_message=summary.error_message,
    )
