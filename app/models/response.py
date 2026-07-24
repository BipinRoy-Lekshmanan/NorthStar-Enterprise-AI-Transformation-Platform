"""Typed models for a retrieval response.

"Response" here means the result of semantic search (ranked chunks +
diagnostics) -- not an LLM-generated answer. Answer generation and
citations are future-milestone concerns.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.models.chunk import Chunk


class RetrievalResult(BaseModel):
    chunk: Chunk
    score: float
    rank: int


class RetrievalDiagnostics(BaseModel):
    query_text: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    total_indexed_chunks: int
    top_k: int
    candidates_considered: int
    embed_latency_ms: float
    search_latency_ms: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RetrievalResponse(BaseModel):
    results: list[RetrievalResult] = Field(default_factory=list)
    diagnostics: RetrievalDiagnostics
