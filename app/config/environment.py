"""Deployment environment model (Milestone 8).

A single, explicit `Environment` concept threaded through configuration
validation -- `staging`/`production` get restrictive, fail-fast checks;
`local`/`development`/`test` stay permissive, matching every prior
milestone's offline-by-default development experience.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Mapping

from app.config.settings import ConfigurationError

DEFAULT_ENVIRONMENT = "local"


class Environment(str, Enum):
    LOCAL = "local"
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_production_like(self) -> bool:
        """`staging` and `production` get restrictive validation;
        `local`/`development`/`test` do not."""
        return self in (Environment.STAGING, Environment.PRODUCTION)


def current_environment(env: Mapping[str, str] | None = None) -> Environment:
    """Reads `APP_ENVIRONMENT`, validated eagerly -- an unrecognized
    value fails fast rather than silently falling back to `local`
    (which would defeat the entire point of restrictive production
    defaults)."""
    env = env if env is not None else os.environ
    raw = env.get("APP_ENVIRONMENT", DEFAULT_ENVIRONMENT).strip().lower()
    try:
        return Environment(raw)
    except ValueError:
        valid = ", ".join(e.value for e in Environment)
        raise ConfigurationError(f"APP_ENVIRONMENT must be one of [{valid}], got '{raw}'.") from None
