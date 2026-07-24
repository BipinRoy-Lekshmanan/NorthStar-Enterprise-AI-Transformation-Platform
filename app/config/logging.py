"""Logging setup for the ingestion pipeline.

Keeps configuration centralized so every module logs consistently and the
level can be controlled via ``LOG_LEVEL`` (see ``app.config.settings``).
"""

from __future__ import annotations

import logging
import os
import sys

from app.config.settings import DEFAULT_LOG_LEVEL

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

_configured = False


def configure_logging(level: str | None = None) -> None:
    """Configure the root logger once per process.

    Reads ``LOG_LEVEL`` directly from the environment (falling back to
    ``DEFAULT_LOG_LEVEL``) rather than via ``IngestionSettings.from_env()``,
    so logging can be set up even before knowledge-base paths are validated
    -- letting configuration errors themselves be logged cleanly.

    Safe to call multiple times; subsequent calls only adjust the level.
    """
    global _configured

    resolved_level = (level or os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL)).strip().upper()

    if _configured:
        logging.getLogger().setLevel(resolved_level)
        return

    logging.basicConfig(
        level=resolved_level,
        format=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
        stream=sys.stdout,
    )
    _configured = True
