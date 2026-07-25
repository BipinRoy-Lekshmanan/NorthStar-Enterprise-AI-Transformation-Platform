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


class PlatformInfoOut(BaseModel):
    version: str
    environment: str
    prompt_version: str
    schema_version: str | None


class ReadinessOut(BaseModel):
    ready: bool
    checks: dict[str, str]


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
    organization_id: str | None = None  # multi-tenant boundary prep (Milestone 8) -- always None today


def build_audit_event_out(event: AuditEvent) -> AuditEventOut:
    return AuditEventOut(
        timestamp=event.timestamp, request_id=event.request_id, actor=event.actor, role=event.role,
        action=event.action, resource_type=event.resource_type, resource_id=event.resource_id,
        outcome=event.outcome, metadata=event.metadata, organization_id=event.organization_id,
    )
