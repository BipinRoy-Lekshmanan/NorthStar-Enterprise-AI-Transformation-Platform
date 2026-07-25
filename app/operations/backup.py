"""Backup/restore for Milestone 8's generated operational state.

In scope: the SQLite operational database (audit/idempotency/
operations/usage events), the vector store, the workflow store, and
the evaluation-run store -- everything that would take real work to
reconstruct after a data-loss event. Deliberately out of scope: the
knowledge-base source documents (tracked in git, the actual source of
truth -- backing them up here would just be a stale duplicate) and the
users file (credentials never belong in a backup archive alongside
other operators' access).

A backup is a single `.zip` archive: `manifest.json` plus one entry per
component. The database is copied via SQLite's own backup API (not a
raw file copy) so a concurrently-open database is captured consistently
-- a raw copy could grab a half-written page if a write is in progress
at the same moment.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

_MANIFEST_FILENAME = "manifest.json"
_DB_BACKUP_FILENAME = "app.db"
_SQLITE_FILE_PREFIX = "sqlite:///"


class BackupError(Exception):
    """Raised for backup/restore failures (missing/invalid archive, an
    unsafe restore target)."""


@dataclass(frozen=True)
class BackupPaths:
    database_url: str
    vector_store_dir: Path
    workflow_store_dir: Path
    evaluation_runs_dir: Path


@dataclass(frozen=True)
class BackupManifest:
    created_at: str
    components: dict[str, int] = field(default_factory=dict)


def _sqlite_path_from_url(database_url: str) -> Path | None:
    if not database_url.startswith(_SQLITE_FILE_PREFIX):
        return None
    return Path(database_url[len(_SQLITE_FILE_PREFIX):])


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    """`ZipFile.extractall()` will happily write outside `destination` if
    a member name contains `../` components ("Zip Slip") -- since
    `restore_backup` takes an archive path from the caller (a human
    running the CLI, but still not guaranteed to be one of *our*
    backups), every member's resolved path is checked to stay within
    `destination` before anything is written."""
    destination = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if target != destination and destination not in target.parents:
            raise BackupError(f"Refusing to extract unsafe archive member path: '{member.filename}'.")
    archive.extractall(destination)


def _backup_sqlite_file(source_db_path: Path, target_db_path: Path) -> None:
    source_conn = sqlite3.connect(str(source_db_path))
    target_conn = sqlite3.connect(str(target_db_path))
    try:
        source_conn.backup(target_conn)
    finally:
        source_conn.close()
        target_conn.close()


def create_backup(destination: Path, paths: BackupPaths) -> Path:
    """Writes a `.zip` archive to `destination` (`.zip` appended if not
    already present; parent directories created as needed) and returns
    the path actually written."""
    if destination.suffix != ".zip":
        destination = destination.with_name(destination.name + ".zip")
    destination.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory() as tmp:
        staging = Path(tmp)
        components: dict[str, int] = {}

        db_path = _sqlite_path_from_url(paths.database_url)
        if db_path is not None and db_path.exists():
            _backup_sqlite_file(db_path, staging / _DB_BACKUP_FILENAME)
            components["database"] = 1

        for name, source_dir in (
            ("vector_store", paths.vector_store_dir),
            ("workflow_store", paths.workflow_store_dir),
            ("evaluation_runs", paths.evaluation_runs_dir),
        ):
            if source_dir.exists():
                target = staging / name
                shutil.copytree(source_dir, target)
                components[name] = sum(1 for p in target.rglob("*") if p.is_file())

        manifest = BackupManifest(created_at=datetime.now(timezone.utc).isoformat(), components=components)
        (staging / _MANIFEST_FILENAME).write_text(
            json.dumps({"created_at": manifest.created_at, "components": manifest.components}, indent=2),
            encoding="utf-8",
        )

        archive_base = str(destination.with_suffix(""))
        shutil.make_archive(archive_base, "zip", root_dir=staging)

    return destination


@dataclass(frozen=True)
class RestoreResult:
    manifest: BackupManifest
    restored_components: list[str]


def _guard_overwrite(target: Path, *, force: bool) -> None:
    if force or not target.exists():
        return
    if target.is_file():
        raise BackupError(f"Refusing to overwrite existing file '{target}' without force=True.")
    if target.is_dir() and any(target.iterdir()):
        raise BackupError(f"Refusing to overwrite non-empty directory '{target}' without force=True.")


def restore_backup(archive_path: Path, paths: BackupPaths, *, force: bool = False) -> RestoreResult:
    """Restores every component present in the archive to its
    configured location. Refuses to overwrite an existing file or a
    non-empty directory unless `force=True` -- a restore is exactly the
    kind of action that should never silently clobber current state."""
    if not archive_path.exists():
        raise BackupError(f"Backup archive not found: '{archive_path}'.")

    with TemporaryDirectory() as tmp:
        staging = Path(tmp)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                _safe_extract(archive, staging)
        except zipfile.BadZipFile as exc:
            raise BackupError(f"'{archive_path}' is not a valid zip archive.") from exc

        manifest_path = staging / _MANIFEST_FILENAME
        if not manifest_path.exists():
            raise BackupError(f"'{archive_path}' is not a valid backup archive (missing manifest.json).")
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = BackupManifest(created_at=manifest_data["created_at"], components=manifest_data["components"])

        restored: list[str] = []

        db_backup = staging / _DB_BACKUP_FILENAME
        db_path = _sqlite_path_from_url(paths.database_url)
        if db_backup.exists() and db_path is not None:
            _guard_overwrite(db_path, force=force)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(db_backup, db_path)
            restored.append("database")

        for name, target_dir in (
            ("vector_store", paths.vector_store_dir),
            ("workflow_store", paths.workflow_store_dir),
            ("evaluation_runs", paths.evaluation_runs_dir),
        ):
            source = staging / name
            if not source.exists():
                continue
            _guard_overwrite(target_dir, force=force)
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source, target_dir)
            restored.append(name)

    return RestoreResult(manifest=manifest, restored_components=restored)
