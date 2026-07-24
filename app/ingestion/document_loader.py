"""Discovers knowledge-base files on disk.

This module is deliberately format-agnostic: it finds candidate files and
hands back their relative paths. Reading/parsing a specific format (e.g.
Markdown) is the job of a dedicated loader such as
:mod:`app.ingestion.markdown_loader`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.config.settings import IngestionSettings

logger = logging.getLogger(__name__)

# Filename prefixes/suffixes conventionally used for generated or lock files
# (e.g. MS Office lock files, build output) that should never be ingested.
_GENERATED_PREFIXES = ("~$",)
_GENERATED_SUFFIXES = (".generated.md", ".tmp")


@dataclass(frozen=True)
class DiscoveredFile:
    """A single file found under a knowledge-base root, ready to be loaded."""

    absolute_path: Path
    relative_path: str  # posix-style path relative to `kb_root`
    kb_root: Path


class DocumentDiscoveryService:
    """Recursively scans configured knowledge-base directories for supported files."""

    def __init__(self, settings: IngestionSettings):
        self._settings = settings

    def discover(self) -> list[DiscoveredFile]:
        """Return discovered files in deterministic order.

        Missing or inaccessible knowledge-base directories are logged as
        errors and skipped rather than raising, so one bad root does not
        prevent discovery in the others. (Directories are also validated
        eagerly in ``IngestionSettings.from_env()``, so this is normally
        a defensive backstop against the path disappearing between
        configuration load and pipeline run.)
        """
        discovered: list[DiscoveredFile] = []

        for kb_root in self._settings.knowledge_base_dirs:
            discovered.extend(self._scan_root(kb_root))

        discovered.sort(key=lambda f: (str(f.kb_root), f.relative_path))
        return discovered

    def _scan_root(self, kb_root: Path) -> list[DiscoveredFile]:
        if not kb_root.exists():
            logger.error("Knowledge base directory not found: %s", kb_root)
            return []
        if not kb_root.is_dir():
            logger.error("Knowledge base path is not a directory: %s", kb_root)
            return []

        found: list[DiscoveredFile] = []
        try:
            candidates = kb_root.rglob("*")
        except OSError as exc:
            logger.error("Unable to scan knowledge base directory %s: %s", kb_root, exc)
            return []

        for path in candidates:
            try:
                if not path.is_file():
                    continue
            except OSError as exc:
                logger.error("Unable to access %s: %s", path, exc)
                continue

            if path.suffix.lower() not in self._settings.supported_extensions:
                continue

            relative_path = path.relative_to(kb_root)
            if self._is_hidden(relative_path) or self._is_generated(path.name):
                continue

            found.append(
                DiscoveredFile(
                    absolute_path=path,
                    relative_path=relative_path.as_posix(),
                    kb_root=kb_root,
                )
            )

        return found

    @staticmethod
    def _is_hidden(relative_path: Path) -> bool:
        return any(part.startswith(".") for part in relative_path.parts)

    @staticmethod
    def _is_generated(filename: str) -> bool:
        if filename.startswith(_GENERATED_PREFIXES):
            return True
        return filename.lower().endswith(_GENERATED_SUFFIXES)
