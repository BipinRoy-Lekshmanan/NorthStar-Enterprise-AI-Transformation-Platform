"""Secret-provider abstraction (Milestone 8).

Every settings class in `app.config.settings` already takes an
`env: Mapping[str, str] | None = None` parameter instead of reading
`os.environ` directly -- that `Mapping[str, str]` *is* this project's
secret-provider extension point. `SecretProvider` formalizes it as a
named type and ships one real implementation (`EnvSecretProvider`, what
every settings class already defaults to when `env=None`) plus one
test-oriented implementation (`StaticSecretProvider`).

A production deployment that wants a real secret manager (AWS Secrets
Manager, HashiCorp Vault, Azure Key Vault, ...) implements
`SecretProvider` once and passes it straight into any
`SomeSettings.from_env(env=my_provider)` call, or
`app.config.production_checks.load_all_settings(env=my_provider)` --
no change to `app.config.settings` is required, since every `from_env`
there only ever calls `.get(key, default)` on whatever `Mapping` it's
given. This module does not ship a cloud-vendor implementation itself
(no new hard dependency) -- only the extension point and its
environment-backed default.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping


class SecretProvider(Mapping[str, str]):
    """A read-only, string-keyed secret source. Satisfies
    `Mapping[str, str]`, so any `SecretProvider` can be passed directly
    as the `env=` argument to any settings class's `from_env()` --
    that Mapping conformance is the entire integration surface."""

    def get_secret(self, key: str, default: str | None = None) -> str | None:
        """Alias for `.get()` with a name that reads clearly at call
        sites that aren't already doing `Mapping`-style access."""
        return self.get(key, default)


class EnvSecretProvider(SecretProvider):
    """Reads from `os.environ` -- what every settings class already
    defaults to today. Snapshots the environment at construction time
    (not a live view), so one instance is a stable, reusable `Mapping`
    even if the process environment changes afterward."""

    def __init__(self, env: Mapping[str, str] | None = None):
        self._data = dict(env if env is not None else os.environ)

    def __getitem__(self, key: str) -> str:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


class StaticSecretProvider(SecretProvider):
    """In-memory `SecretProvider` -- lets a test build an isolated
    secret source without `monkeypatch.setenv` touching the real
    process environment."""

    def __init__(self, values: Mapping[str, str]):
        self._data = dict(values)

    def __getitem__(self, key: str) -> str:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)
