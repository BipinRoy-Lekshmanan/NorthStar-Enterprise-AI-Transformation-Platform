"""Audit event model (Milestone 7).

Records significant user actions -- never full prompts, full answers,
secrets, or full document content. Enough to reconstruct "who did what,
when, to what, with what outcome," never enough to reconstruct the
actual conversation or document text.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditEvent(BaseModel):
    timestamp: datetime = Field(default_factory=_utcnow)
    request_id: str | None = None
    actor: str
    role: str
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    outcome: str = "success"
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Multi-tenant boundary prep (Milestone 8): always None today -- this
    # platform has exactly one tenant, and nothing filters or scopes by
    # this field anywhere. It exists so a future multi-tenant milestone
    # can start populating and querying by it without another schema
    # change to the audit log (app.db.models.AuditEventRecord already
    # has the matching column).
    organization_id: str | None = None
