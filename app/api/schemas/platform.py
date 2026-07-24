"""Request/response schemas for platform diagnostic endpoints (Milestone 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.audit.models import AuditEvent


class HealthDetailOut(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    components: dict[str, str]
    advisor_count: int
    workflow_count: int


class AuditEventOut(BaseModel):
    timestamp: datetime
    request_id: str | None
    actor: str
    role: str
    action: str
    resource_type: str | None
    resource_id: str | None
    outcome: str
    metadata: dict[str, Any]


def build_audit_event_out(event: AuditEvent) -> AuditEventOut:
    return AuditEventOut(
        timestamp=event.timestamp, request_id=event.request_id, actor=event.actor, role=event.role,
        action=event.action, resource_type=event.resource_type, resource_id=event.resource_id,
        outcome=event.outcome, metadata=event.metadata,
    )
