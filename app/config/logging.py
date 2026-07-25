"""Logging setup (Milestones 1 and 8).

Keeps configuration centralized so every module logs consistently.
``LOG_LEVEL`` controls verbosity (Milestone 1); ``LOG_FORMAT``
(Milestone 8) selects ``text`` (human-readable, the default in
``local``/``development``/``test``) or ``json`` (the default in
``staging``/``production``) -- structured records carry ``timestamp``,
``level``, ``environment``, ``service``, ``application_version``, the
current request's correlation id, and whatever extra fields a call site
passes via ``logger.info(msg, extra={...})`` (``execution_id``,
``workflow_id``, ``actor_role``, ``duration_ms``, etc.), redacted
through the same ``app.config.redaction.redact()`` used by
``python -m app.config show``.

Request-id propagation uses a ``contextvars.ContextVar`` rather than
threading a parameter through every function call: `set_request_id()`
is called once, at the top of ``RequestContextMiddleware``, and every
log line emitted anywhere during that request -- including deep inside
``app.api.services`` -- picks it up automatically via
``RequestIdFilter``. This is additive to (not a replacement for) the
explicit ``request_id`` parameters `AuditContext`/audit events already
carry, since those are persisted records that must remain correct even
if logging is reconfigured or disabled.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
from datetime import datetime, timezone

from app.config.settings import DEFAULT_LOG_LEVEL

SERVICE_NAME = "northstar-platform"

_TEXT_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

# Attribute names a bare `logging.LogRecord` already carries -- anything
# else on a record's `__dict__` came from a caller's `extra={...}` and
# belongs in the structured payload.
_STANDARD_LOGRECORD_ATTRS = frozenset(vars(logging.LogRecord("x", 0, "x", 0, "x", (), None)).keys()) | {
    "message", "asctime", "taskName",
}

_configured = False

_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def set_request_id(request_id: str | None) -> contextvars.Token:
    """Called once per request, at the top of `RequestContextMiddleware`.
    Returns a token for `reset_request_id()` so the value doesn't leak
    past the request that set it."""
    return _request_id_var.set(request_id)


def reset_request_id(token: contextvars.Token) -> None:
    _request_id_var.reset(token)


def get_request_id() -> str | None:
    return _request_id_var.get()


class RequestIdFilter(logging.Filter):
    """Injects the current request's correlation id into every record
    that doesn't already carry one via explicit `extra={"request_id": ...}`."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, environment: str, application_version: str):
        super().__init__()
        self._environment = environment
        self._application_version = application_version

    def format(self, record: logging.LogRecord) -> str:
        from app.config.redaction import redact  # deferred: avoids importing redaction at module-import time

        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "environment": self._environment,
            "service": SERVICE_NAME,
            "application_version": self._application_version,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOGRECORD_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), default=str)


def _resolve_log_format(explicit_format: str | None) -> str:
    if explicit_format:
        return explicit_format.strip().lower()
    raw = os.environ.get("LOG_FORMAT")
    if raw:
        return raw.strip().lower()

    from app.config.environment import current_environment  # deferred: avoids a load at import time

    return "json" if current_environment().is_production_like else "text"


def configure_logging(level: str | None = None, log_format: str | None = None) -> None:
    """Configure the root logger once per process.

    Reads ``LOG_LEVEL``/``LOG_FORMAT`` directly from the environment
    (falling back to defaults) rather than via a settings class, so
    logging can be set up even before knowledge-base paths are
    validated -- letting configuration errors themselves be logged
    cleanly.

    Safe to call multiple times; subsequent calls only adjust the level.
    """
    global _configured

    resolved_level = (level or os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL)).strip().upper()
    resolved_format = _resolve_log_format(log_format)

    if _configured:
        logging.getLogger().setLevel(resolved_level)
        return

    from app.api.version import APP_VERSION
    from app.config.environment import current_environment

    handler = logging.StreamHandler(sys.stdout)
    if resolved_format == "json":
        handler.setFormatter(JsonFormatter(environment=current_environment().value, application_version=APP_VERSION))
    else:
        handler.setFormatter(logging.Formatter(_TEXT_LOG_FORMAT, datefmt=_DATE_FORMAT))
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(resolved_level)
    _configured = True
