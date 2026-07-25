"""`python -m app.operations backup|restore|cleanup` (Milestone 8)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config.settings import DatabaseSettings, EvaluationSettings, RetrievalSettings, WorkflowSettings
from app.db.engine import build_engine, build_session_factory, create_all
from app.operations.backup import BackupError, BackupPaths, create_backup, restore_backup
from app.operations.cleanup import run_cleanup


def _paths_from_env() -> BackupPaths:
    return BackupPaths(
        database_url=DatabaseSettings.from_env().database_url,
        vector_store_dir=RetrievalSettings.from_env().vector_store_dir,
        workflow_store_dir=WorkflowSettings.from_env().workflow_store_dir,
        evaluation_runs_dir=EvaluationSettings.from_env().evaluation_runs_dir,
    )


def _run_backup(args: argparse.Namespace) -> int:
    archive = create_backup(Path(args.destination), _paths_from_env())
    print(f"Backup written to {archive}")
    return 0


def _run_restore(args: argparse.Namespace) -> int:
    try:
        result = restore_backup(Path(args.archive), _paths_from_env(), force=args.force)
    except BackupError as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Restored from backup created at {result.manifest.created_at}")
    print(f"Restored components: {', '.join(result.restored_components) or '(none)'}")
    return 0


def _run_cleanup(args: argparse.Namespace) -> int:
    paths = _paths_from_env()
    engine = build_engine(paths.database_url)
    # Safety net, same rationale as app.api.main's lifespan: a dev/test
    # environment that never ran `python -m app.db upgrade` still works.
    create_all(engine)
    session_factory = build_session_factory(engine)
    report = run_cleanup(
        workflow_store_dir=paths.workflow_store_dir, evaluation_runs_dir=paths.evaluation_runs_dir,
        session_factory=session_factory, retention_days=args.retention_days, dry_run=args.dry_run,
    )
    verb = "Would delete" if args.dry_run else "Deleted"
    print(f"{verb} {len(report.deleted_files)} file(s):")
    for path in report.deleted_files:
        print(f"  {path}")
    print(f"{verb} {report.deleted_idempotency_records} expired idempotency record(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.operations", description="Backup/restore/cleanup for generated operational state.",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    backup_parser = subparsers.add_parser("backup", help="Create a backup archive.")
    backup_parser.add_argument("--destination", required=True, help="Output .zip path.")

    restore_parser = subparsers.add_parser("restore", help="Restore from a backup archive.")
    restore_parser.add_argument("--archive", required=True, help="Path to a .zip backup archive.")
    restore_parser.add_argument(
        "--force", action="store_true", help="Overwrite existing non-empty restore targets.",
    )

    cleanup_parser = subparsers.add_parser("cleanup", help="Delete generated state older than --retention-days.")
    cleanup_parser.add_argument("--retention-days", type=int, required=True)
    cleanup_parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be deleted without deleting anything.",
    )

    args = parser.parse_args(argv)
    if args.action == "backup":
        return _run_backup(args)
    if args.action == "restore":
        return _run_restore(args)
    return _run_cleanup(args)


if __name__ == "__main__":
    sys.exit(main())
