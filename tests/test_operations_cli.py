"""Tests for `python -m app.operations backup|restore|cleanup` (Milestone 8).

Every test isolates DATABASE_URL/VECTOR_STORE_DIR/WORKFLOW_STORE_DIR/
EVALUATION_RUNS_DIR to tmp_path via monkeypatch -- never the real
project directories.
"""

import os
import time

from app.operations import cli as operations_cli


def _set_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    monkeypatch.setenv("VECTOR_STORE_DIR", str(tmp_path / "vector_store"))
    monkeypatch.setenv("WORKFLOW_STORE_DIR", str(tmp_path / "workflow_store"))
    monkeypatch.setenv("EVALUATION_RUNS_DIR", str(tmp_path / "evaluation_runs"))


def _age_file(path, days_old):
    old_time = time.time() - days_old * 86400
    os.utime(path, (old_time, old_time))


def test_backup_then_restore_round_trip_via_cli(tmp_path, monkeypatch, capsys):
    _set_env(monkeypatch, tmp_path)
    (tmp_path / "workflow_store").mkdir()
    (tmp_path / "workflow_store" / "exec-1.json").write_text('{"execution_id": "exec-1"}', encoding="utf-8")

    archive_path = tmp_path / "backups" / "b1"
    exit_code = operations_cli.main(["backup", "--destination", str(archive_path)])
    assert exit_code == 0
    assert "Backup written to" in capsys.readouterr().out

    # Restoring into the SAME location without --force must be rejected --
    # the directory it's restoring into already has this exact content.
    exit_code = operations_cli.main(["restore", "--archive", str(archive_path) + ".zip"])
    assert exit_code == 1
    assert "ERROR" in capsys.readouterr().out

    exit_code = operations_cli.main(["restore", "--archive", str(archive_path) + ".zip", "--force"])
    assert exit_code == 0
    assert "Restored components" in capsys.readouterr().out


def test_cleanup_dry_run_via_cli_reports_without_deleting(tmp_path, monkeypatch, capsys):
    _set_env(monkeypatch, tmp_path)
    workflow_dir = tmp_path / "workflow_store"
    workflow_dir.mkdir()
    old_file = workflow_dir / "old.json"
    old_file.write_text("{}", encoding="utf-8")
    _age_file(old_file, days_old=40)

    exit_code = operations_cli.main(["cleanup", "--retention-days", "30", "--dry-run"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Would delete 1 file" in output
    assert old_file.exists()


def test_cleanup_real_run_via_cli_deletes(tmp_path, monkeypatch, capsys):
    _set_env(monkeypatch, tmp_path)
    workflow_dir = tmp_path / "workflow_store"
    workflow_dir.mkdir()
    old_file = workflow_dir / "old.json"
    old_file.write_text("{}", encoding="utf-8")
    _age_file(old_file, days_old=40)

    exit_code = operations_cli.main(["cleanup", "--retention-days", "30"])

    assert exit_code == 0
    assert "Deleted 1 file" in capsys.readouterr().out
    assert not old_file.exists()


def test_restore_missing_archive_via_cli_reports_error(tmp_path, monkeypatch, capsys):
    _set_env(monkeypatch, tmp_path)
    exit_code = operations_cli.main(["restore", "--archive", str(tmp_path / "nope.zip")])
    assert exit_code == 1
    assert "ERROR" in capsys.readouterr().out
