"""Local persistent store for `WorkflowExecution` state (Milestone 6).

One JSON file per execution, `<workflow_store_dir>/<execution_id>.json`
-- the same "plain files in a directory, no external DB" shape as
`app.embeddings.vector_store.LocalVectorStore`. Written far more often
than the vector store (once per stage, not once per index build), so
`save()` writes to a temp file and renames into place rather than
writing the target file directly -- a crash mid-write can never leave a
truncated, unloadable execution record behind.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.models.workflow import WorkflowExecution

_SUFFIX = ".json"
_TEMP_SUFFIX = ".json.tmp"


class WorkflowStoreError(Exception):
    """Raised for invalid workflow-store operations (missing execution, corrupt file)."""


class WorkflowStore:
    def __init__(self, directory: Path):
        self._directory = directory
        self._directory.mkdir(parents=True, exist_ok=True)

    def _path(self, execution_id: str) -> Path:
        return self._directory / f"{execution_id}{_SUFFIX}"

    def save(self, execution: WorkflowExecution) -> None:
        path = self._path(execution.execution_id)
        temp_path = self._directory / f"{execution.execution_id}{_TEMP_SUFFIX}"
        temp_path.write_text(json.dumps(execution.model_dump(mode="json"), indent=2), encoding="utf-8")
        os.replace(temp_path, path)

    def load(self, execution_id: str) -> WorkflowExecution:
        path = self._path(execution_id)
        if not path.exists():
            raise WorkflowStoreError(f"No workflow execution found for id '{execution_id}'.")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WorkflowStoreError(f"Execution file for '{execution_id}' is corrupt: {exc}") from exc
        return WorkflowExecution.model_validate(raw)

    def exists(self, execution_id: str) -> bool:
        return self._path(execution_id).exists()

    def list_execution_ids(self) -> list[str]:
        return sorted(path.stem for path in self._directory.glob(f"*{_SUFFIX}"))
