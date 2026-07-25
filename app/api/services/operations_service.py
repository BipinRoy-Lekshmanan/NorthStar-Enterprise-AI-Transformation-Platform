"""Application service for the background operations API (Milestone 8).

Thin facade -- `start_knowledge_rebuild` wraps the exact same
`run_full_rebuild` service function the synchronous
`POST /knowledge/rebuild` endpoint calls (Milestone 7/Task 95's rebuild
lock and all) into a zero-arg closure for `OperationRunner`. No rebuild
logic is duplicated; this only changes *how* the caller finds out the
result -- poll `GET /operations/{id}` instead of waiting on the
response.
"""

from __future__ import annotations

from app.api.services.knowledge_service import run_full_rebuild
from app.config.settings import IngestionSettings, RetrievalSettings
from app.operations.background import OperationRunner, OperationSummary
from app.resilience.concurrency import LockRegistry

KNOWLEDGE_REBUILD_OPERATION_TYPE = "knowledge_rebuild"


def start_knowledge_rebuild(
    runner: OperationRunner, lock_registry: LockRegistry, ingestion_settings: IngestionSettings,
    retrieval_settings: RetrievalSettings, *, created_by: str | None = None,
) -> str:
    def _run() -> dict:
        report = run_full_rebuild(ingestion_settings, retrieval_settings, lock_registry=lock_registry)
        return {"added": report.added, "removed": report.removed, "unchanged": report.unchanged, "total": report.total}

    return runner.start(KNOWLEDGE_REBUILD_OPERATION_TYPE, _run, created_by=created_by)


def get_operation(runner: OperationRunner, operation_id: str) -> OperationSummary:
    return runner.get_operation(operation_id)


def list_operations(
    runner: OperationRunner, *, operation_type: str | None = None, status: str | None = None,
) -> list[OperationSummary]:
    return runner.list_operations(operation_type=operation_type, status=status)
