"""Tests for `app.operations.backup` (Milestone 8) -- create/restore a
backup archive against tmp_path-isolated directories, never the real
project's data/workflow_store/vector_store/evaluation_runs.
"""

import sqlite3

import pytest

from app.operations.backup import BackupError, BackupPaths, create_backup, restore_backup


def _make_source_tree(tmp_path):
    db_path = tmp_path / "source" / "app.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO t (value) VALUES ('hello')")
    conn.commit()
    conn.close()

    vector_store_dir = tmp_path / "source" / "vector_store"
    vector_store_dir.mkdir()
    (vector_store_dir / "index_state.json").write_text('{"total": 1}', encoding="utf-8")

    workflow_store_dir = tmp_path / "source" / "workflow_store"
    workflow_store_dir.mkdir()
    (workflow_store_dir / "exec-1.json").write_text('{"execution_id": "exec-1"}', encoding="utf-8")

    evaluation_runs_dir = tmp_path / "source" / "evaluation_runs"
    evaluation_runs_dir.mkdir()
    (evaluation_runs_dir / "run-1.json").write_text('{"run_id": "run-1"}', encoding="utf-8")

    return BackupPaths(
        database_url=f"sqlite:///{db_path.as_posix()}",
        vector_store_dir=vector_store_dir, workflow_store_dir=workflow_store_dir,
        evaluation_runs_dir=evaluation_runs_dir,
    )


def test_create_backup_writes_a_zip_with_every_component(tmp_path):
    paths = _make_source_tree(tmp_path)

    archive = create_backup(tmp_path / "backups" / "b1", paths)

    assert archive.exists()
    assert archive.suffix == ".zip"


def test_create_backup_appends_zip_suffix_if_missing(tmp_path):
    paths = _make_source_tree(tmp_path)
    archive = create_backup(tmp_path / "backups" / "b1.zip", paths)
    assert archive.name == "b1.zip"


def test_restore_backup_round_trips_every_component_into_fresh_targets(tmp_path):
    source_paths = _make_source_tree(tmp_path)
    archive = create_backup(tmp_path / "backups" / "b1", source_paths)

    restore_target_db = tmp_path / "restored" / "app.db"
    restore_paths = BackupPaths(
        database_url=f"sqlite:///{restore_target_db.as_posix()}",
        vector_store_dir=tmp_path / "restored" / "vector_store",
        workflow_store_dir=tmp_path / "restored" / "workflow_store",
        evaluation_runs_dir=tmp_path / "restored" / "evaluation_runs",
    )

    result = restore_backup(archive, restore_paths)

    assert set(result.restored_components) == {"database", "vector_store", "workflow_store", "evaluation_runs"}
    assert restore_target_db.exists()
    conn = sqlite3.connect(str(restore_target_db))
    assert conn.execute("SELECT value FROM t").fetchone() == ("hello",)
    conn.close()
    assert (restore_paths.workflow_store_dir / "exec-1.json").read_text(encoding="utf-8") == '{"execution_id": "exec-1"}'
    assert (restore_paths.evaluation_runs_dir / "run-1.json").exists()
    assert (restore_paths.vector_store_dir / "index_state.json").exists()


def test_restore_refuses_to_overwrite_a_non_empty_directory_without_force(tmp_path):
    source_paths = _make_source_tree(tmp_path)
    archive = create_backup(tmp_path / "backups" / "b1", source_paths)

    existing_workflow_dir = tmp_path / "restored" / "workflow_store"
    existing_workflow_dir.mkdir(parents=True)
    (existing_workflow_dir / "already-here.json").write_text("{}", encoding="utf-8")

    restore_paths = BackupPaths(
        database_url=f"sqlite:///{(tmp_path / 'restored' / 'app.db').as_posix()}",
        vector_store_dir=tmp_path / "restored" / "vector_store",
        workflow_store_dir=existing_workflow_dir,
        evaluation_runs_dir=tmp_path / "restored" / "evaluation_runs",
    )

    with pytest.raises(BackupError, match="non-empty"):
        restore_backup(archive, restore_paths)

    # Untouched -- the guard fired before anything was overwritten.
    assert (existing_workflow_dir / "already-here.json").exists()


def test_restore_with_force_overwrites_existing_data(tmp_path):
    source_paths = _make_source_tree(tmp_path)
    archive = create_backup(tmp_path / "backups" / "b1", source_paths)

    existing_workflow_dir = tmp_path / "restored" / "workflow_store"
    existing_workflow_dir.mkdir(parents=True)
    (existing_workflow_dir / "stale.json").write_text("{}", encoding="utf-8")

    restore_paths = BackupPaths(
        database_url=f"sqlite:///{(tmp_path / 'restored' / 'app.db').as_posix()}",
        vector_store_dir=tmp_path / "restored" / "vector_store",
        workflow_store_dir=existing_workflow_dir,
        evaluation_runs_dir=tmp_path / "restored" / "evaluation_runs",
    )

    result = restore_backup(archive, restore_paths, force=True)

    assert "workflow_store" in result.restored_components
    assert not (existing_workflow_dir / "stale.json").exists()
    assert (existing_workflow_dir / "exec-1.json").exists()


def test_restore_missing_archive_raises(tmp_path):
    paths = BackupPaths(
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        vector_store_dir=tmp_path / "vector_store", workflow_store_dir=tmp_path / "workflow_store",
        evaluation_runs_dir=tmp_path / "evaluation_runs",
    )
    with pytest.raises(BackupError, match="not found"):
        restore_backup(tmp_path / "does_not_exist.zip", paths)


def test_restore_rejects_a_non_backup_zip(tmp_path):
    import zipfile

    bogus = tmp_path / "bogus.zip"
    with zipfile.ZipFile(bogus, "w") as archive:
        archive.writestr("not_a_manifest.txt", "hello")

    paths = BackupPaths(
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        vector_store_dir=tmp_path / "vector_store", workflow_store_dir=tmp_path / "workflow_store",
        evaluation_runs_dir=tmp_path / "evaluation_runs",
    )
    with pytest.raises(BackupError, match="manifest"):
        restore_backup(bogus, paths)


def test_restore_rejects_a_zip_slip_archive(tmp_path):
    import zipfile

    malicious = tmp_path / "malicious.zip"
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("manifest.json", '{"created_at": "now", "components": {}}')
        archive.writestr("../../evil.txt", "pwned")

    paths = BackupPaths(
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        vector_store_dir=tmp_path / "vector_store", workflow_store_dir=tmp_path / "workflow_store",
        evaluation_runs_dir=tmp_path / "evaluation_runs",
    )
    with pytest.raises(BackupError, match="unsafe archive member"):
        restore_backup(malicious, paths)

    assert not (tmp_path.parent / "evil.txt").exists()


def test_create_backup_skips_missing_components_gracefully(tmp_path):
    paths = BackupPaths(
        database_url=f"sqlite:///{(tmp_path / 'does_not_exist' / 'app.db').as_posix()}",
        vector_store_dir=tmp_path / "does_not_exist_vs", workflow_store_dir=tmp_path / "does_not_exist_ws",
        evaluation_runs_dir=tmp_path / "does_not_exist_er",
    )

    archive = create_backup(tmp_path / "backups" / "empty", paths)

    assert archive.exists()
    restore_paths = BackupPaths(
        database_url=f"sqlite:///{(tmp_path / 'restored' / 'app.db').as_posix()}",
        vector_store_dir=tmp_path / "restored" / "vector_store",
        workflow_store_dir=tmp_path / "restored" / "workflow_store",
        evaluation_runs_dir=tmp_path / "restored" / "evaluation_runs",
    )
    result = restore_backup(archive, restore_paths)
    assert result.restored_components == []
