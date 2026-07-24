"""Reads individual Markdown files into `LoadedDocument` models.

Every failure mode (missing file, permission error, non-UTF-8 content) is
caught and turned into a `DocumentLoadError` instead of raising, so a
single bad file never aborts the ingestion run.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from app.ingestion.document_loader import DiscoveredFile
from app.ingestion.metadata_extractor import extract_metadata
from app.models.document import DocumentLoadError, DocumentMetadata, LoadedDocument

logger = logging.getLogger(__name__)


class MarkdownLoader:
    """Loads a single discovered Markdown file, tolerating per-file failures."""

    def load(self, discovered: DiscoveredFile) -> LoadedDocument | DocumentLoadError:
        try:
            raw_bytes = discovered.absolute_path.read_bytes()
        except OSError as exc:
            logger.error("Unable to read %s: %s", discovered.relative_path, exc)
            return DocumentLoadError(source_path=discovered.relative_path, error=str(exc))

        try:
            content = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            logger.error("Unable to decode %s as UTF-8: %s", discovered.relative_path, exc)
            return DocumentLoadError(
                source_path=discovered.relative_path, error=f"invalid UTF-8: {exc}"
            )

        # Normalize line endings so frontmatter/heading parsing (and chunk
        # offsets) behave identically regardless of the authoring platform.
        content = content.replace("\r\n", "\n").replace("\r", "\n")

        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        modified_time = self._read_modified_time(discovered)
        metadata = self._extract_metadata(content, discovered.relative_path)

        return LoadedDocument(
            source_file=discovered.absolute_path.name,
            source_path=discovered.relative_path,
            content=content,
            content_hash=content_hash,
            modified_time=modified_time,
            metadata=metadata,
        )

    @staticmethod
    def _read_modified_time(discovered: DiscoveredFile) -> datetime | None:
        try:
            return datetime.fromtimestamp(
                discovered.absolute_path.stat().st_mtime, tz=timezone.utc
            )
        except OSError as exc:
            logger.warning(
                "Unable to read modified time for %s: %s", discovered.relative_path, exc
            )
            return None

    @staticmethod
    def _extract_metadata(content: str, relative_path: str) -> DocumentMetadata:
        try:
            return extract_metadata(content, relative_path)
        except Exception as exc:  # metadata issues must not fail the whole document
            logger.error("Metadata extraction failed for %s: %s", relative_path, exc)
            return DocumentMetadata()
