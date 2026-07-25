"""Single source of truth for the app version/prefix (Milestone 7).

A tiny standalone module so `app.api.services.platform_service` can
report the running version without importing `app.api.main` (which
itself imports the route modules, which import the services -- an
import from a service back into `main` would be circular).

Kept in sync with `pyproject.toml`'s `[project].version` by hand (no
build tooling reads one from the other today).
"""

from __future__ import annotations

APP_VERSION = "0.8.0"
API_PREFIX = "/api/v1"
