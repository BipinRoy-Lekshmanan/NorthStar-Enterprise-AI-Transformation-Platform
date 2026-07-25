"""Feature flags (Milestone 8).

A single `FEATURE_FLAGS` environment variable holds a comma-separated
list of `name=true|false` pairs (e.g. `FEATURE_FLAGS=background_operations=false`),
parsed once into a small settings object. Deliberately minimal: no
per-user/per-request targeting, no remote flag service -- a portfolio
reference implementation's operational toggles are static per
deployment, not a full experimentation platform.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.config.settings import ConfigurationError, parse_bool


@dataclass(frozen=True)
class FeatureFlagSettings:
    flags: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "FeatureFlagSettings":
        env = env if env is not None else os.environ
        raw = env.get("FEATURE_FLAGS", "").strip()
        if not raw:
            return cls(flags={})

        flags: dict[str, bool] = {}
        for pair in raw.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if "=" not in pair:
                raise ConfigurationError(
                    f"FEATURE_FLAGS entries must be 'name=true' or 'name=false', got '{pair}'."
                )
            name, _, raw_value = pair.partition("=")
            name = name.strip()
            if not name:
                raise ConfigurationError(f"FEATURE_FLAGS entry '{pair}' is missing a flag name.")
            if not raw_value.strip():
                raise ConfigurationError(f"FEATURE_FLAGS entry '{name}' is missing a boolean value.")
            try:
                flags[name] = parse_bool({"value": raw_value}, "value", False)
            except ConfigurationError as exc:
                raise ConfigurationError(f"FEATURE_FLAGS entry '{name}': {exc}") from exc
        return cls(flags=flags)

    def is_enabled(self, name: str, default: bool = False) -> bool:
        return self.flags.get(name, default)
