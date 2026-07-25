"""Tests for `app.operations.cleanup` (Milestone 8)."""

import os
import time
from datetime import datetime, timedelta, timezone

from app.db.engine import build_engine, build_session_factory, create_all, session_scope
from app.db.models import IdempotencyRecord
from app.operations.cleanup import cleanup_directory, cleanup_expired_idempotency_records, run_cleanup


def _age_file(path, days_old):
    old_time = time.time() - days_old * 86400
    os.utime(path, (old_time, old_time))


def test_cleanup_directory_dry_run_reports_without_deleting(tmp_path):
    directory = tmp_path / "workflow_store"
    directory.mkdir()
    old_file = directory / "old.json"
    old_file.write_text("{}", encoding="utf-8")
    _age_file(old_file, days_old=40)

    deleted = cleanup_directory(directory, retention_days=30, dry_run=True)

    assert deleted == [str(old_file)]
    assert old_file.exists()  # dry run never deletes


def test_cleanup_directory_real_run_deletes_old_files_only(tmp_path):
    directory = tmp_path / "workflow_store"
    directory.mkdir()
    old_file = directory / "old.json"
    old_file.write_text("{}", encoding="utf-8")
    _age_file(old_file, days_old=40)
    recent_file = directory / "recent.json"
    recent_file.write_text("{}", encoding="utf-8")

    deleted = cleanup_directory(directory, retention_days=30, dry_run=False)

    assert deleted == [str(old_file)]
    assert not old_file.exists()
    assert recent_file.exists()


def test_cleanup_directory_on_missing_directory_returns_empty(tmp_path):
    assert cleanup_directory(tmp_path / "does_not_exist", retention_days=30, dry_run=True) == []


def _session_factory(tmp_path):
    engine = build_engine(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    create_all(engine)
    return build_session_factory(engine)


def test_cleanup_expired_idempotency_records_dry_run_does_not_delete(tmp_path):
    session_factory = _session_factory(tmp_path)
    now = datetime.now(timezone.utc)
    with session_scope(session_factory) as session:
        session.add(
            IdempotencyRecord(
                idempotency_key="k1", endpoint="e1", request_hash="h1", response_status=200,
                response_body={}, expires_at=now - timedelta(days=1),
            )
        )

    count = cleanup_expired_idempotency_records(session_factory, dry_run=True)

    assert count == 1
    with session_scope(session_factory) as session:
        assert session.query(IdempotencyRecord).count() == 1


def test_cleanup_expired_idempotency_records_real_run_deletes_only_expired(tmp_path):
    session_factory = _session_factory(tmp_path)
    now = datetime.now(timezone.utc)
    with session_scope(session_factory) as session:
        session.add(
            IdempotencyRecord(
                idempotency_key="expired", endpoint="e1", request_hash="h1", response_status=200,
                response_body={}, expires_at=now - timedelta(days=1),
            )
        )
        session.add(
            IdempotencyRecord(
                idempotency_key="fresh", endpoint="e1", request_hash="h2", response_status=200,
                response_body={}, expires_at=now + timedelta(days=1),
            )
        )

    count = cleanup_expired_idempotency_records(session_factory, dry_run=False)

    assert count == 1
    with session_scope(session_factory) as session:
        remaining = session.query(IdempotencyRecord).all()
        assert len(remaining) == 1
        assert remaining[0].idempotency_key == "fresh"


def test_run_cleanup_combines_files_and_idempotency_records(tmp_path):
    workflow_store_dir = tmp_path / "workflow_store"
    workflow_store_dir.mkdir()
    old_execution = workflow_store_dir / "old-exec.json"
    old_execution.write_text("{}", encoding="utf-8")
    _age_file(old_execution, days_old=40)

    evaluation_runs_dir = tmp_path / "evaluation_runs"
    evaluation_runs_dir.mkdir()
    old_run = evaluation_runs_dir / "old-run.json"
    old_run.write_text("{}", encoding="utf-8")
    _age_file(old_run, days_old=40)

    session_factory = _session_factory(tmp_path)
    with session_scope(session_factory) as session:
        session.add(
            IdempotencyRecord(
                idempotency_key="expired", endpoint="e1", request_hash="h1", response_status=200,
                response_body={}, expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )

    report = run_cleanup(
        workflow_store_dir=workflow_store_dir, evaluation_runs_dir=evaluation_runs_dir,
        session_factory=session_factory, retention_days=30, dry_run=False,
    )

    assert report.dry_run is False
    assert set(report.deleted_files) == {str(old_execution), str(old_run)}
    assert report.deleted_idempotency_records == 1
    assert not old_execution.exists()
    assert not old_run.exists()
