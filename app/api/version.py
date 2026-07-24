"""Single source of truth for the app version/prefix (Milestone 7).

A tiny standalone module so `app.api.services.platform_service` can
report the running version without importing `app.api.main` (which
itself imports the route modules, which import the services -- an
import from a service back into `main` would be circular).
"""

from __future__ import annotations

APP_VERSION = "0.7.0"
API_PREFIX = "/api/v1"
