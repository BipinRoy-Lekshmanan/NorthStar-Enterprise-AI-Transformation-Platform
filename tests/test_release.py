"""Tests for `app.release` (Milestone 8) -- release readiness
validation and SBOM generation.
"""

import json

import pytest

from app.db.cli import alembic_config
from app.release import cli as release_cli
from app.release import validate as validate_module
from app.release.sbom import SbomGenerationError, generate_sbom
from app.release.validate import (
    _check_schema_migration_state,
    _check_version_consistency,
    validate_release,
)


def _set_clean_env(monkeypatch, tmp_path, **overrides):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir(exist_ok=True)
    (kb_dir / "doc.md").write_text("# Doc\n\ncontent", encoding="utf-8")

    env = {
        "KNOWLEDGE_BASE_DIRS": str(kb_dir),
        "VECTOR_STORE_DIR": str(tmp_path / "vector_store"),
        "WORKFLOW_STORE_DIR": str(tmp_path / "workflow_store"),
        "AUDIT_LOG_DIR": str(tmp_path / "audit_log"),
        "EVALUATION_RUNS_DIR": str(tmp_path / "evaluation_runs"),
        "INGESTION_OUTPUT_DIR": str(tmp_path / "processed"),
        "DATABASE_URL": f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
    }
    if "AUTH_USERS_FILE" not in overrides:
        users_file = tmp_path / "users.json"
        users_file.write_text(
            json.dumps([{"api_key": "a-real-rotated-key", "username": "admin", "role": "administrator"}]),
            encoding="utf-8",
        )
        env["AUTH_USERS_FILE"] = str(users_file)

    env.update(overrides)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


# -- _check_version_consistency -----------------------------------------------------------------------------


def test_version_consistency_passes_for_the_real_repo():
    # app/api/version.py's APP_VERSION is kept in sync with
    # pyproject.toml by hand -- this is a real regression guard for
    # exactly the staleness bug Task #107 found and fixed.
    assert _check_version_consistency() is None


def test_version_consistency_detects_a_mismatch(monkeypatch):
    monkeypatch.setattr(validate_module, "APP_VERSION", "99.99.99")
    issue = _check_version_consistency()
    assert issue is not None
    assert "99.99.99" in issue


# -- _check_schema_migration_state -----------------------------------------------------------------------------


def _sqlite_url(tmp_path, name="app.db"):
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def test_schema_check_is_none_for_a_nonexistent_database(tmp_path):
    assert _check_schema_migration_state(_sqlite_url(tmp_path)) is None


def test_schema_check_passes_when_database_is_at_head(tmp_path, monkeypatch):
    from alembic import command

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(tmp_path))
    command.upgrade(alembic_config(), "head")

    assert _check_schema_migration_state(_sqlite_url(tmp_path)) is None


def test_schema_check_detects_a_behind_head_database(tmp_path, monkeypatch):
    from alembic import command

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(tmp_path))
    # Stamp the first real revision only, not HEAD -- a database that's
    # behind what the code's migrations expect.
    command.stamp(alembic_config(), "d420aa223a1d")

    issue = _check_schema_migration_state(_sqlite_url(tmp_path))

    assert issue is not None
    assert "d420aa223a1d" in issue
    assert "python -m app.db upgrade" in issue


# -- validate_release / CLI -----------------------------------------------------------------------------


def _example_users_file(tmp_path):
    users_file = tmp_path / "example_users.json"
    users_file.write_text(
        json.dumps([{"api_key": "viewer-example-key-change-me", "username": "v", "role": "viewer"}]),
        encoding="utf-8",
    )
    return str(users_file)


def test_validate_release_returns_ready_with_warnings_for_default_example_keys(monkeypatch, tmp_path):
    _set_clean_env(monkeypatch, tmp_path, AUTH_USERS_FILE=_example_users_file(tmp_path))
    result = validate_release()
    assert any("default/example credential" in p for p in result.problems)
    assert result.environment.value == "local"


def test_cli_validate_returns_0_with_warnings_in_local(monkeypatch, tmp_path, capsys):
    _set_clean_env(monkeypatch, tmp_path, AUTH_USERS_FILE=_example_users_file(tmp_path))
    exit_code = release_cli._run_validate()
    assert exit_code == 0
    assert "READY_WITH_WARNINGS" in capsys.readouterr().out


def test_cli_validate_returns_0_ready_with_no_warnings_for_a_fully_clean_environment(monkeypatch, tmp_path, capsys):
    _set_clean_env(monkeypatch, tmp_path)
    exit_code = release_cli._run_validate()
    assert exit_code == 0
    assert "READY:" in capsys.readouterr().out


def test_cli_validate_returns_1_when_configuration_is_invalid(monkeypatch, tmp_path, capsys):
    _set_clean_env(monkeypatch, tmp_path, API_PORT="99999")
    exit_code = release_cli._run_validate()
    assert exit_code == 1
    assert "NOT_READY" in capsys.readouterr().out


def test_cli_sbom_writes_a_valid_cyclonedx_document(tmp_path):
    output_path = tmp_path / "sbom.json"
    exit_code = release_cli.main(["sbom", "--output", str(output_path)])

    assert exit_code == 0
    assert output_path.exists()
    document = json.loads(output_path.read_text(encoding="utf-8"))
    assert document["bomFormat"] == "CycloneDX"
    assert document["components"]


def test_generate_sbom_raises_on_a_failing_subprocess(tmp_path, monkeypatch):
    import subprocess as subprocess_module

    def _fake_run(*args, **kwargs):
        return subprocess_module.CompletedProcess(args=args, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr("app.release.sbom.subprocess.run", _fake_run)

    with pytest.raises(SbomGenerationError, match="boom"):
        generate_sbom(tmp_path / "sbom.json")
