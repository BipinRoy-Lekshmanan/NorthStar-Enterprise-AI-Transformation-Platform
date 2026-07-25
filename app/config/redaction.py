"""Central secret/PII redaction (Milestone 8).

One function, reused by structured logging (`app/config/logging.py`),
`python -m app.config show --redacted`, and anywhere else a dict needs
to be made safe to print/log/return. Redacts by *key name* (a
case-insensitive substring match against a fixed marker list),
recursively through nested dicts/lists/tuples -- simple, predictable,
and works without knowing the shape of what's being redacted.
"""

from __future__ import annotations

from typing import Any

REDACTED_VALUE = "***REDACTED***"

SENSITIVE_KEY_MARKERS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
    "cookie",
    "session",
    "credential",
)

# Substring matching over-redacts real, non-secret config fields whose
# names happen to contain a marker as part of an unrelated word --
# found live via `python -m app.config show --redacted`, which redacted
# `llm_max_output_tokens` (a plain integer limit) because "token" is a
# substring of "tokens". Checked before the marker scan.
SAFE_KEY_ALLOWLIST: frozenset[str] = frozenset({
    "max_output_tokens",
    "llm_max_output_tokens",
    "input_tokens",
    "output_tokens",
})


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in SAFE_KEY_ALLOWLIST:
        return False
    return any(marker in lowered for marker in SENSITIVE_KEY_MARKERS)


def redact(value: Any) -> Any:
    """Returns a copy of `value` with sensitive dict values replaced by
    `REDACTED_VALUE`. Non-container values pass through unchanged --
    call this on the container that *holds* the sensitive field, not on
    a bare string, since redaction is key-name-driven."""
    if isinstance(value, dict):
        return {
            key: (REDACTED_VALUE if is_sensitive_key(str(key)) else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value
