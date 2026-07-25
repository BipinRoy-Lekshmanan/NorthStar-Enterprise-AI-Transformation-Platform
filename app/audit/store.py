"""SQLite-backed, hash-chained audit log persistence (Milestone 8,
superseding Milestone 7's append-only JSONL file).

Each event is chained to the one before it: `current_hash` is a SHA-256
digest over `(sequence_number, previous_hash, timestamp, actor, role,
action, resource_type, resource_id, request_id, outcome, metadata,
organization_id)`, and
`previous_hash` is the prior event's `current_hash` (`None` for the
first event). `verify_chain()` walks every event in sequence and
recomputes the digest -- any edited, deleted-and-reinserted, or
reordered row breaks the chain at that point, which is the property an
audit log needs: not just "what happened" but "has this record been
tampered with since."

Writes are serialized by an in-process lock (not just relying on
SQLite's own locking) so `sequence_number`/`previous_hash` assignment
is race-free under concurrent requests -- reading "last row" and
inserting "next row" must happen as one logical step, the same
correctness concern `LockRegistry` exists for elsewhere in Milestone 8.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import desc
from sqlalchemy.orm import Session, sessionmaker

from app.audit.models import AuditEvent
from app.config.settings import DatabaseSettings
from app.db.engine import build_engine, build_session_factory, create_all, session_scope
from app.db.models import AuditEventRecord


def _as_aware_utc(value: datetime) -> datetime:
    """Same rationale as `app.resilience.idempotency._as_aware_utc`:
    SQLite doesn't reliably round-trip timezone-aware datetimes, so a
    naive value read back is treated as UTC (the only timezone this
    module ever writes) -- otherwise the hash recomputed at verify time
    would differ from the one computed at write time through no actual
    tampering."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _compute_hash(
    *, sequence_number: int, previous_hash: str | None, timestamp: datetime, actor: str, role: str | None,
    action: str, resource_type: str | None, resource_id: str | None, request_id: str | None,
    outcome: str, metadata: dict, organization_id: str | None = None,
) -> str:
    canonical = json.dumps(
        {
            "sequence_number": sequence_number,
            "previous_hash": previous_hash,
            "timestamp": _as_aware_utc(timestamp).isoformat(),
            "actor": actor,
            "role": role,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "request_id": request_id,
            "outcome": outcome,
            "metadata": metadata,
            "organization_id": organization_id,
        },
        sort_keys=True, default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _to_audit_event(record: AuditEventRecord) -> AuditEvent:
    return AuditEvent(
        timestamp=record.timestamp, request_id=record.request_id, actor=record.actor, role=record.role or "",
        action=record.action, resource_type=record.resource_type, resource_id=record.resource_id,
        outcome=record.outcome, metadata=record.event_metadata, organization_id=record.organization_id,
    )


@dataclass(frozen=True)
class ChainVerificationResult:
    valid: bool
    total_events: int
    first_invalid_sequence: int | None = None
    reason: str | None = None


class AuditStore:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory
        self._write_lock = threading.Lock()

    @classmethod
    def from_env(cls, database_url: str | None = None) -> "AuditStore":
        """Convenience constructor mirroring the other Milestone 8
        settings classes' `from_env()` -- builds its own engine, creating
        the schema as a safety net if migrations haven't run yet."""
        engine = build_engine(database_url or DatabaseSettings.from_env().database_url)
        create_all(engine)
        return cls(build_session_factory(engine))

    def record(self, event: AuditEvent) -> None:
        with self._write_lock, session_scope(self._session_factory) as session:
            last = session.query(AuditEventRecord).order_by(desc(AuditEventRecord.sequence_number)).first()
            sequence_number = (last.sequence_number if last else 0) + 1
            previous_hash = last.current_hash if last else None
            current_hash = _compute_hash(
                sequence_number=sequence_number, previous_hash=previous_hash, timestamp=event.timestamp,
                actor=event.actor, role=event.role, action=event.action, resource_type=event.resource_type,
                resource_id=event.resource_id, request_id=event.request_id, outcome=event.outcome,
                metadata=event.metadata, organization_id=event.organization_id,
            )
            session.add(
                AuditEventRecord(
                    event_id=str(uuid.uuid4()), sequence_number=sequence_number, timestamp=event.timestamp,
                    actor=event.actor, role=event.role, action=event.action, resource_type=event.resource_type,
                    resource_id=event.resource_id, outcome=event.outcome, request_id=event.request_id,
                    event_metadata=event.metadata, organization_id=event.organization_id,
                    previous_hash=previous_hash, current_hash=current_hash,
                )
            )

    def list_events(self, limit: int | None = None) -> list[AuditEvent]:
        """Returns events most-recent-first, optionally capped at `limit`."""
        with session_scope(self._session_factory) as session:
            query = session.query(AuditEventRecord).order_by(desc(AuditEventRecord.sequence_number))
            if limit is not None:
                query = query.limit(limit)
            return [_to_audit_event(record) for record in query.all()]

    def verify_chain(self) -> ChainVerificationResult:
        """Walks every event in sequence order and recomputes its hash --
        `valid=False` on the first record whose stored `current_hash`
        doesn't match what its content actually hashes to (edited data)
        or whose `previous_hash` doesn't match the prior record's
        `current_hash` (reordered or spliced-in data)."""
        with session_scope(self._session_factory) as session:
            records = session.query(AuditEventRecord).order_by(AuditEventRecord.sequence_number).all()
            previous_hash: str | None = None
            for record in records:
                if record.previous_hash != previous_hash:
                    return ChainVerificationResult(
                        valid=False, total_events=len(records), first_invalid_sequence=record.sequence_number,
                        reason=f"sequence {record.sequence_number}: previous_hash does not match the prior event.",
                    )
                expected = _compute_hash(
                    sequence_number=record.sequence_number, previous_hash=record.previous_hash,
                    timestamp=record.timestamp, actor=record.actor, role=record.role, action=record.action,
                    resource_type=record.resource_type, resource_id=record.resource_id,
                    request_id=record.request_id, outcome=record.outcome, metadata=record.event_metadata,
                    organization_id=record.organization_id,
                )
                if record.current_hash != expected:
                    return ChainVerificationResult(
                        valid=False, total_events=len(records), first_invalid_sequence=record.sequence_number,
                        reason=f"sequence {record.sequence_number}: stored hash does not match its recorded content.",
                    )
                previous_hash = record.current_hash
            return ChainVerificationResult(valid=True, total_events=len(records))
