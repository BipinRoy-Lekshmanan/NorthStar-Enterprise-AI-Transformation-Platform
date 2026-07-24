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
