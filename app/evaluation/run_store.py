"""Local persistent store for `EvaluationRun` history (Milestone 7).

One JSON file per run, `<evaluation_runs_dir>/<run_id>.json` -- the
same "plain files in a directory, no external DB, write-to-temp-then-
rename" shape as `app.workflows.store.WorkflowStore`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.evaluation.run_models import EvaluationRun

_SUFFIX = ".json"
_TEMP_SUFFIX = ".json.tmp"


class EvaluationRunStoreError(Exception):
    """Raised for invalid evaluation-run-store operations (missing run, corrupt file)."""


class EvaluationRunStore:
    def __init__(self, directory: Path):
        self._directory = directory
        self._directory.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        return self._directory / f"{run_id}{_SUFFIX}"

    def save(self, run: EvaluationRun) -> None:
        path = self._path(run.run_id)
        temp_path = self._directory / f"{run.run_id}{_TEMP_SUFFIX}"
        temp_path.write_text(json.dumps(run.model_dump(mode="json"), indent=2), encoding="utf-8")
        os.replace(temp_path, path)

    def load(self, run_id: str) -> EvaluationRun:
        path = self._path(run_id)
        if not path.exists():
            raise EvaluationRunStoreError(f"No evaluation run found for id '{run_id}'.")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise EvaluationRunStoreError(f"Run file for '{run_id}' is corrupt: {exc}") from exc
        return EvaluationRun.model_validate(raw)

    def list_run_ids(self) -> list[str]:
        return sorted(path.stem for path in self._directory.glob(f"*{_SUFFIX}"))
