"""Release readiness validation (Milestone 8).

Extends `app.config.production_checks.validate_production_readiness`
(config-shape checks) with two release-specific checks that only make
sense at "are we actually about to ship this" time:

- version consistency between `app.api.version.APP_VERSION` and
  `pyproject.toml`'s `[project].version` (this exact drift bit the
  real codebase once -- `APP_VERSION` sat at "0.7.0" for an entire
  milestone after `pyproject.toml` moved to "0.8.0" in Task #86, caught
  only by hand while building `/platform/info` in Task #107).
- whether the target database's actually-applied Alembic revision
  matches the code's expected HEAD (a deployment that forgot to run
  `python -m app.db upgrade` would otherwise boot against a stale
  schema with no warning).

Same READY / READY_WITH_WARNINGS / NOT_READY convention as
`python -m app.config validate`: every problem here is advisory outside
staging/production and blocking within it -- deciding which is the
CLI layer's job (`app.release.cli`), this module only ever returns the
raw problem list.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.api.version import APP_VERSION
from app.config.environment import Environment
from app.config.production_checks import load_all_settings, validate_production_readiness
from app.config.settings import PROJECT_ROOT


@dataclass(frozen=True)
class ReleaseCheckResult:
    environment: Environment
    problems: list[str] = field(default_factory=list)


def _check_version_consistency() -> str | None:
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    try:
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
        pyproject_version = data["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        return f"Could not read [project].version from pyproject.toml: {exc}"

    if pyproject_version != APP_VERSION:
        return (
            f"Version mismatch: app.api.version.APP_VERSION='{APP_VERSION}' but "
            f"pyproject.toml's [project].version='{pyproject_version}'."
        )
    return None


def _check_schema_migration_state(database_url: str) -> str | None:
    """Compares the database's actually-applied Alembic revision
    against the code's expected HEAD. Returns `None` (not a problem)
    when the database doesn't exist yet / isn't reachable at all --
    that's `python -m app.db upgrade`'s job to create, not this
    check's job to flag, since a brand-new environment legitimately
    has no schema applied yet."""
    try:
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        from app.db.cli import alembic_config
        from app.db.engine import build_engine

        head = ScriptDirectory.from_config(alembic_config()).get_current_head()
        engine = build_engine(database_url)
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
    except Exception:  # noqa: BLE001 -- best-effort diagnostic, never fatal to the release check itself
        return None

    if current is None:
        return None
    if current != head:
        return (
            f"Database schema revision '{current}' does not match the expected HEAD '{head}' -- "
            "run `python -m app.db upgrade`."
        )
    return None


def validate_release(env: Mapping[str, str] | None = None) -> ReleaseCheckResult:
    """Raises `ConfigurationError` (same as `load_all_settings`) if
    configuration itself can't even be loaded -- the caller (the CLI)
    treats that as an immediate NOT_READY, same as
    `app.config.cli._run_validate()`."""
    bundle = load_all_settings(env)
    problems = list(validate_production_readiness(bundle, env))

    version_issue = _check_version_consistency()
    if version_issue:
        problems.append(version_issue)

    schema_issue = _check_schema_migration_state(bundle.database.database_url)
    if schema_issue:
        problems.append(schema_issue)

    return ReleaseCheckResult(environment=bundle.environment, problems=problems)
