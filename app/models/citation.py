"""Typed model for a structured citation.

Built only for source identifiers the model actually referenced in its
answer -- see `app.rag.citation_engine`. Never fabricated: every field
traces back to a real retrieved `Chunk`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Citation(BaseModel):
    source_id: str
    chunk_id: str
    document_title: str | None = None
    document_id: str | None = None
    source_file: str
    source_path: str
    section_title: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    score: float
    excerpt: str
