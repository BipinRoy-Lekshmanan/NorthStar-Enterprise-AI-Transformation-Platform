"""Convenience wrapper for recording an audit event (Milestone 7).

Called directly by `app.api.services` functions after a significant
action -- routes never touch the audit store, they only supply the
identity/request context via an `AuditContext`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.audit.models import AuditEvent
from app.audit.store import AuditStore


@dataclass(frozen=True)
class AuditContext:
    """Bundles what a service needs to record an event, resolved once by
    the route layer from its own auth/request-context dependencies.

    `organization_id` is multi-tenant boundary prep (Milestone 8): always
    `None` today (nothing populates or filters by it), but the field
    exists so a future multi-tenant milestone can start threading a real
    tenant id through here without another signature change."""

    store: AuditStore
    actor: str
    role: str
    request_id: str | None = None
    organization_id: str | None = None


def record_event(
    store: AuditStore,
    *,
    actor: str,
    role: str,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    outcome: str = "success",
    request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    organization_id: str | None = None,
) -> None:
    event = AuditEvent(
        request_id=request_id,
        actor=actor,
        role=role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        metadata=metadata or {},
        organization_id=organization_id,
    )
    store.record(event)


def record_from_context(
    context: AuditContext | None,
    *,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    outcome: str = "success",
    metadata: dict[str, Any] | None = None,
) -> None:
    """No-op when `context` is `None` -- lets service functions accept an
    optional audit context without an `if context:` guard at every call site."""
    if context is None:
        return
    record_event(
        context.store,
        actor=context.actor,
        role=context.role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        request_id=context.request_id,
        metadata=metadata,
        organization_id=context.organization_id,
    )
