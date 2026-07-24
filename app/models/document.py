"""Typed models for discovered and loaded knowledge-base documents."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """Metadata extracted from a document's YAML frontmatter.

    Every field is optional: not all Northstar documents carry a
    frontmatter block, and not all frontmatter blocks carry every field.
    """

    document_id: str | None = None
    title: str | None = None
    owner: str | None = None
    version: str | None = None
    status: str | None = None
    classification: str | None = None
    review_cycle: str | None = None
    effective_date: str | None = None
    related_documents: list[str] = Field(default_factory=list)
    # Any frontmatter keys not modeled explicitly above (forward-compatible).
    extra: dict[str, Any] = Field(default_factory=dict)


class LoadedDocument(BaseModel):
    """A successfully loaded Markdown document, ready for chunking."""

    source_file: str
    source_path: str
    content: str
    content_hash: str
    modified_time: datetime | None = None
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)


class DocumentLoadError(BaseModel):
    """Records why a discovered file could not be loaded, without halting the run."""

    source_path: str
    error: str
