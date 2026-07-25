"""Tests for `app.config.production_checks` (Milestone 8)."""

import json

import pytest

from app.config.environment import Environment
from app.config.production_checks import load_all_settings, validate_production_readiness
from app.config.settings import ConfigurationError


def _base_env(tmp_path, **overrides):
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
    # hasn't supplied their own AUTH_USERS_FILE override -- otherwise
    # this would clobber a file the test already prepared at the same
    # default path.
    if "AUTH_USERS_FILE" not in overrides:
        users_file = tmp_path / "users.json"
        users_file.write_text(
            json.dumps([{"api_key": "a-real-rotated-key", "username": "admin", "role": "administrator"}]),
            encoding="utf-8",
        )
        env["AUTH_USERS_FILE"] = str(users_file)

    env.update(overrides)
    return env


def test_load_all_settings_succeeds_with_a_clean_environment(tmp_path):
    bundle = load_all_settings(env=_base_env(tmp_path))
    assert bundle.environment == Environment.LOCAL


def test_validate_production_readiness_clean_bundle_has_no_problems(tmp_path):
    bundle = load_all_settings(env=_base_env(tmp_path))
    problems = validate_production_readiness(bundle)
    assert problems == []


def test_debug_true_is_flagged(tmp_path):
    bundle = load_all_settings(env=_base_env(tmp_path, DEBUG="true"))
    problems = validate_production_readiness(bundle)
    assert any("DEBUG" in p for p in problems)


def test_wildcard_cors_is_flagged(tmp_path):
    bundle = load_all_settings(env=_base_env(tmp_path, API_CORS_ORIGINS="*"))
    problems = validate_production_readiness(bundle)
    assert any("CORS" in p for p in problems)


def test_openai_llm_provider_without_key_fails_at_settings_load_not_here(tmp_path):
    # RagSettings.validate() (Milestone 3) already rejects this, in every
    # environment -- validate_production_readiness() never needs to
    # re-check it because load_all_settings() never returns a bundle
    # that violates it.
    with pytest.raises(ConfigurationError, match="LLM_API_KEY"):
        load_all_settings(env=_base_env(tmp_path, LLM_PROVIDER="openai"))


def test_openai_embedding_provider_without_key_fails_at_settings_load_not_here(tmp_path):
    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        load_all_settings(env=_base_env(tmp_path, EMBEDDING_PROVIDER="openai"))


def test_default_credential_marker_is_flagged(tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps([{"api_key": "viewer-example-key-change-me", "username": "v", "role": "viewer"}]),
        encoding="utf-8",
    )
    bundle = load_all_settings(env=_base_env(tmp_path, AUTH_USERS_FILE=str(users_file)))
    problems = validate_production_readiness(bundle)
    assert any("default/example credential" in p for p in problems)


def test_missing_users_file_is_flagged(tmp_path):
    bundle = load_all_settings(env=_base_env(tmp_path, AUTH_USERS_FILE=str(tmp_path / "does_not_exist.json")))
    problems = validate_production_readiness(bundle)
    assert any("AUTH_USERS_FILE is not usable" in p for p in problems)


def test_allowed_llm_models_rejects_unlisted_model(tmp_path):
    env = _base_env(tmp_path, ALLOWED_LLM_MODELS="gpt-4o")
    bundle = load_all_settings(env=env)
    problems = validate_production_readiness(bundle, env=env)
    assert any("LLM_MODEL" in p for p in problems)


def test_allowed_llm_models_accepts_listed_model(tmp_path):
    env = _base_env(tmp_path, ALLOWED_LLM_MODELS="fake-echo-v1")
    bundle = load_all_settings(env=env)
    problems = validate_production_readiness(bundle, env=env)
    assert not any("LLM_MODEL" in p for p in problems)


def test_no_allow_list_configured_means_unrestricted(tmp_path):
    env = _base_env(tmp_path)
    bundle = load_all_settings(env=env)
    problems = validate_production_readiness(bundle, env=env)
    assert not any("LLM_MODEL" in p for p in problems)
