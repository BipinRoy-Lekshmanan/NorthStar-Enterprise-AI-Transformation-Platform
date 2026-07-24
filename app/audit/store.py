"""Append-only audit log persistence (Milestone 7).

A single growing JSON Lines file under `audit_log/` -- mirrors
`WorkflowStore`'s "plain files, no external DB" shape. Each event is
appended as one line; unlike `WorkflowStore` (which rewrites a whole
execution file per save and so uses a temp-write-then-rename), an
append-only log just opens in append mode and writes one line at a
time -- a single `write()` call of one JSON line is already atomic at
the OS level for typical log-line sizes, and there's no existing file
content to protect against corrupting.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.audit.models import AuditEvent

_LOG_FILENAME = "events.jsonl"


class AuditStore:
    def __init__(self, directory: Path):
        self._directory = directory
        self._directory.mkdir(parents=True, exist_ok=True)
        self._path = self._directory / _LOG_FILENAME

    def record(self, event: AuditEvent) -> None:
        line = json.dumps(event.model_dump(mode="json"))
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def list_events(self, limit: int | None = None) -> list[AuditEvent]:
        """Returns events most-recent-first, optionally capped at `limit`."""
        if not self._path.exists():
            return []

        events: list[AuditEvent] = []
        with self._path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                events.append(AuditEvent.model_validate(json.loads(raw_line)))

        events.reverse()
        if limit is not None:
            events = events[:limit]
        return events
