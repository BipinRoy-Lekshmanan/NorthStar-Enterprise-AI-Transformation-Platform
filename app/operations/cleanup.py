"""Retention cleanup for generated operational state (Milestone 8).

Age for a workflow-execution/evaluation-run file is judged by its
mtime -- both stores write a file once at creation and again on each
subsequent state change (`WorkflowStore.save`/`EvaluationRunStore.save`
both overwrite in place), so mtime faithfully reflects "last touched,"
not just "first created." Idempotency records use their own
`expires_at` column instead, already tracked by
`app.resilience.idempotency`.

`dry_run` defaults to `True` in every function here -- a caller (the
CLI, a test) must explicitly opt in to real deletion.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.db.engine import session_scope
from app.db.models import IdempotencyRecord

_SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class CleanupReport:
    dry_run: bool
    deleted_files: list[str] = field(default_factory=list)
    deleted_idempotency_records: int = 0


def cleanup_directory(directory: Path, *, retention_days: int, dry_run: bool = True) -> list[str]:
    if not directory.exists():
        return []
    cutoff = time.time() - retention_days * _SECONDS_PER_DAY
    deleted: list[str] = []
    for path in sorted(directory.glob("*.json")):
        if path.stat().st_mtime < cutoff:
            deleted.append(str(path))
            if not dry_run:
                path.unlink()
    return deleted


def cleanup_expired_idempotency_records(session_factory: sessionmaker[Session], *, dry_run: bool = True) -> int:
    now = datetime.now(timezone.utc)
    with session_scope(session_factory) as session:
        query = session.query(IdempotencyRecord).filter(IdempotencyRecord.expires_at < now)
        count = query.count()
        if not dry_run:
            query.delete(synchronize_session=False)
    return count


def run_cleanup(
    *, workflow_store_dir: Path, evaluation_runs_dir: Path, session_factory: sessionmaker[Session],
    retention_days: int, dry_run: bool = True,
) -> CleanupReport:
    deleted_files = cleanup_directory(workflow_store_dir, retention_days=retention_days, dry_run=dry_run)
    deleted_files += cleanup_directory(evaluation_runs_dir, retention_days=retention_days, dry_run=dry_run)
    deleted_idempotency = cleanup_expired_idempotency_records(session_factory, dry_run=dry_run)
    return CleanupReport(dry_run=dry_run, deleted_files=deleted_files, deleted_idempotency_records=deleted_idempotency)
