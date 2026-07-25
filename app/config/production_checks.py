"""Aggregate settings loading + production-readiness validation (Milestone 8).

`load_all_settings()` calls every existing Milestone 1-7 settings
class's own `from_env()` -- each already validates itself eagerly and
raises `ConfigurationError` on any invalid value, in every environment.
`validate_production_readiness()` adds *additional*, environment-aware
checks that only make sense in aggregate (e.g. "is the configured LLM
provider's API key actually present," "does this directory accept a
write") -- these are advisory in `local`/`development`/`test` and
fail-fast in `staging`/`production`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from app.auth.users import UserDirectoryError, load_users
from app.config.environment import Environment, current_environment
from app.config.settings import (
    ApiSettings,
    AuthSettings,
    EvaluationSettings,
    IngestionSettings,
    RagSettings,
    RetrievalSettings,
    RouterSettings,
    WorkflowSettings,
)

# A default/example credential is anything whose key literally contains
# one of these substrings -- matches the fake keys committed in
# data/auth/users.example.json (e.g. "viewer-example-key-change-me").
_DEFAULT_CREDENTIAL_MARKERS = ("change-me", "example-key", "changeme")


@dataclass(frozen=True)
class SettingsBundle:
    environment: Environment
    ingestion: IngestionSettings
    retrieval: RetrievalSettings
    rag: RagSettings
    router: RouterSettings
    workflow: WorkflowSettings
    api: ApiSettings
    auth: AuthSettings
    evaluation: EvaluationSettings


def load_all_settings(env: Mapping[str, str] | None = None) -> SettingsBundle:
    """Builds every settings class from `env` (defaults to `os.environ`).
    Raises `ConfigurationError` from whichever class's own `.validate()`
    rejects it first -- the same fail-fast behavior every prior
    milestone already relies on, just gathered into one call."""
    return SettingsBundle(
        environment=current_environment(env),
        ingestion=IngestionSettings.from_env(env),
        retrieval=RetrievalSettings.from_env(env),
        rag=RagSettings.from_env(env),
        router=RouterSettings.from_env(env),
        workflow=WorkflowSettings.from_env(env),
        api=ApiSettings.from_env(env),
        auth=AuthSettings.from_env(env),
        evaluation=EvaluationSettings.from_env(env),
    )


def _writable_directories(bundle: SettingsBundle) -> list[tuple[str, Path]]:
    return [
        ("VECTOR_STORE_DIR", bundle.retrieval.vector_store_dir),
        ("WORKFLOW_STORE_DIR", bundle.workflow.workflow_store_dir),
        ("AUDIT_LOG_DIR", bundle.api.audit_log_dir),
        ("EVALUATION_RUNS_DIR", bundle.evaluation.evaluation_runs_dir),
    ]


def _check_directory_writable(name: str, path: Path) -> str | None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_check"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return f"{name} ('{path}') is not writable: {exc}"
    return None


def _allowed_models_violation(env: Mapping[str, str] | None, list_var: str, configured_value: str, label: str) -> str | None:
    env = env if env is not None else os.environ
    raw = env.get(list_var, "").strip()
    if not raw:
        return None  # no allow-list configured -- unrestricted
    allowed = {item.strip() for item in raw.split(",") if item.strip()}
    if configured_value not in allowed:
        return f"{label} '{configured_value}' is not in {list_var} ({sorted(allowed)})."
    return None


def validate_production_readiness(bundle: SettingsBundle, env: Mapping[str, str] | None = None) -> list[str]:
    """Returns a list of human-readable problems (empty = safe). Never
    raises -- callers decide whether to treat the list as fatal (the
    CLI does, only in staging/production; `python -m app.config
    validate` shows it as advisory information otherwise)."""
    problems: list[str] = []

    if bundle.api.debug:
        problems.append("DEBUG must be False outside local/development/test.")

    if "*" in bundle.api.cors_allowed_origins:
        problems.append("API_CORS_ORIGINS must not include the wildcard '*' outside local/development/test.")

    # Note: "LLM_API_KEY required when LLM_PROVIDER=openai" and its
    # embedding-provider equivalent are NOT re-checked here -- `RagSettings`/
    # `RetrievalSettings.validate()` (Milestone 2/3) already raise
    # `ConfigurationError` for these, in every environment, at
    # `load_all_settings()` time. Re-checking here would be dead code:
    # `validate_production_readiness()` never runs with a bundle that
    # violates them.

    for name, path in _writable_directories(bundle):
        issue = _check_directory_writable(name, path)
        if issue:
            problems.append(issue)

    try:
        users = load_users(bundle.auth.users_file)
    except UserDirectoryError as exc:
        problems.append(f"AUTH_USERS_FILE is not usable: {exc}")
    else:
        if not users:
            problems.append("AUTH_USERS_FILE contains no users.")
        default_keys = [
            api_key for api_key in users
            if any(marker in api_key.lower() for marker in _DEFAULT_CREDENTIAL_MARKERS)
        ]
        if default_keys:
            problems.append(
                f"AUTH_USERS_FILE contains {len(default_keys)} default/example credential(s) "
                "(matched 'change-me'/'example-key') -- replace with real keys."
            )

    for issue in (
        _allowed_models_violation(env, "ALLOWED_LLM_MODELS", bundle.rag.llm_model, "LLM_MODEL"),
        _allowed_models_violation(env, "ALLOWED_EMBEDDING_MODELS", bundle.retrieval.embedding_model, "EMBEDDING_MODEL"),
    ):
        if issue:
            problems.append(issue)

    return problems
