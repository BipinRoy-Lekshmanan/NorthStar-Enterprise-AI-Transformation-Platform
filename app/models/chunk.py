"""Typed model for a Markdown-aware document chunk.

Chunks are the structured output of Milestone 1: plain data, ready to be
consumed by a future embedding step without any further parsing.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    chunk_id: str
    text: str
    chunk_index: int
    document_title: str | None = None
    document_id: str | None = None
    source_file: str
    source_path: str
    section_title: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    content_hash: str
    char_count: int
