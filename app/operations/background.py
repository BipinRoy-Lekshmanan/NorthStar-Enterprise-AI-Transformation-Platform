"""`OperationRunner` -- starts a zero-arg callable on a background
daemon thread, tracking its lifecycle (`pending` -> `running` ->
`completed`/`failed`) in the `operations` SQLite table
(`app.db.models.Operation`).

`func` itself is responsible for its own correctness under concurrency
-- e.g. `run_full_rebuild` already takes a `LockRegistry` to reject a
second concurrent rebuild, so a caller starting two background rebuilds
back-to-back gets the second one recorded as `failed` with a clear
`CONCURRENCY_CONFLICT` error message, not silent double-processing.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import desc
from sqlalchemy.orm import Session, sessionmaker

from app.db.engine import session_scope
from app.db.models import Operation


class UnknownOperationError(KeyError):
    """Raised when an operation_id doesn't match any recorded operation."""


@dataclass(frozen=True)
class OperationSummary:
    operation_id: str
    operation_type: str
    status: str
    created_by: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result: dict | None
    error_message: str | None


def _to_summary(record: Operation) -> OperationSummary:
    return OperationSummary(
        operation_id=record.operation_id, operation_type=record.operation_type, status=record.status,
        created_by=record.created_by, created_at=record.created_at, started_at=record.started_at,
        completed_at=record.completed_at, result=record.result, error_message=record.error_message,
    )


class OperationRunner:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def start(self, operation_type: str, func: Callable[[], dict], *, created_by: str | None = None) -> str:
        """Records a `pending` operation row, then immediately starts
        `func` on a background thread and returns the new
        `operation_id` -- never blocks for `func`'s duration."""
        operation_id = str(uuid.uuid4())
        with session_scope(self._session_factory) as session:
            session.add(
                Operation(
                    operation_id=operation_id, operation_type=operation_type, status="pending",
                    created_by=created_by, created_at=datetime.now(timezone.utc),
                )
            )

        thread = threading.Thread(
            target=self._run, args=(operation_id, func), name=f"operation-{operation_id}", daemon=True,
        )
        thread.start()
        return operation_id

    def _run(self, operation_id: str, func: Callable[[], dict]) -> None:
        self._update(operation_id, status="running", started_at=datetime.now(timezone.utc))
        try:
            result = func()
        except Exception as exc:
            self._update(
                operation_id, status="failed", completed_at=datetime.now(timezone.utc),
                error_message=f"{type(exc).__name__}: {exc}",
            )
            return
        self._update(operation_id, status="completed", completed_at=datetime.now(timezone.utc), result=result)

    def _update(self, operation_id: str, **fields: object) -> None:
        with session_scope(self._session_factory) as session:
            record = session.query(Operation).filter_by(operation_id=operation_id).one()
            for key, value in fields.items():
                setattr(record, key, value)

    def get_operation(self, operation_id: str) -> OperationSummary:
        with session_scope(self._session_factory) as session:
            record = session.query(Operation).filter_by(operation_id=operation_id).one_or_none()
            if record is None:
                raise UnknownOperationError(f"Unknown operation_id '{operation_id}'.")
            return _to_summary(record)

    def list_operations(
        self, *, operation_type: str | None = None, status: str | None = None,
    ) -> list[OperationSummary]:
        with session_scope(self._session_factory) as session:
            query = session.query(Operation)
            if operation_type is not None:
                query = query.filter_by(operation_type=operation_type)
            if status is not None:
                query = query.filter_by(status=status)
            query = query.order_by(desc(Operation.created_at))
            return [_to_summary(record) for record in query.all()]
