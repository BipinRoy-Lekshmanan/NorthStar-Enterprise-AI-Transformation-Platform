"""Tests for `app.config.cli` (Milestone 8) -- `python -m app.config
validate|show`. Tests call `_run_validate()`/`_run_show()` directly
(these read `os.environ` via `load_all_settings(env=None)`), with
`monkeypatch.setenv` isolating each test to a tmp_path environment.
"""

import json

from app.config.cli import _run_show, _run_validate


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
    }

    # Only write the default (real-looking) users file when the caller
    # hasn't supplied their own AUTH_USERS_FILE override -- otherwise this
    # would clobber a file the test already prepared at the same path.
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


def test_validate_returns_zero_for_clean_local_environment(monkeypatch, tmp_path, capsys):
    _set_clean_env(monkeypatch, tmp_path)
    exit_code = _run_validate()
    assert exit_code == 0
    assert "READY" in capsys.readouterr().out


def test_validate_returns_zero_with_warnings_when_defaults_present_locally(monkeypatch, tmp_path, capsys):
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps([{"api_key": "viewer-example-key-change-me", "username": "v", "role": "viewer"}]),
        encoding="utf-8",
    )
    _set_clean_env(monkeypatch, tmp_path, AUTH_USERS_FILE=str(users_file))
    exit_code = _run_validate()
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "READY_WITH_WARNINGS" in output


def test_validate_fails_in_production_with_default_credentials(monkeypatch, tmp_path, capsys):
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps([{"api_key": "viewer-example-key-change-me", "username": "v", "role": "viewer"}]),
        encoding="utf-8",
    )
    _set_clean_env(monkeypatch, tmp_path, AUTH_USERS_FILE=str(users_file), APP_ENVIRONMENT="production")
    exit_code = _run_validate()
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "NOT_READY" in output


def test_validate_fails_fast_on_invalid_environment_value(monkeypatch, tmp_path, capsys):
    _set_clean_env(monkeypatch, tmp_path, APP_ENVIRONMENT="bogus")
    exit_code = _run_validate()
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "NOT_READY" in output


def test_show_prints_valid_json_with_secrets_redacted(monkeypatch, tmp_path, capsys):
    _set_clean_env(monkeypatch, tmp_path, LLM_PROVIDER="openai", LLM_API_KEY="sk-real-secret-value")
    exit_code = _run_show()
    output = capsys.readouterr().out
    assert exit_code == 0

    body = json.loads(output)
    assert body["rag"]["llm_api_key"] == "***REDACTED***"
    assert "sk-real-secret-value" not in output
    assert body["rag"]["llm_max_output_tokens"] == 1024


def test_show_returns_nonzero_on_configuration_error(monkeypatch, tmp_path, capsys):
    _set_clean_env(monkeypatch, tmp_path, API_PORT="99999")
    exit_code = _run_show()
    assert exit_code == 1
