"""Typed models for retrieval and grounded-RAG responses.

`RetrievalResponse` (Milestone 2) is the result of semantic search alone.
`RagAnswer` (Milestone 3) is the result of the full grounded workflow --
retrieval + bounded context + LLM generation + citation parsing.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.models.chunk import Chunk
from app.models.citation import Citation


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


class RagDiagnostics(BaseModel):
    request_id: str
    retrieval_duration_ms: float
    embed_duration_ms: float
    search_duration_ms: float
    retrieved_chunk_count: int
    context_chunk_count: int
    chunks_excluded: int
    highest_retrieval_score: float | None = None
    model_provider: str | None = None
    model_name: str | None = None
    model_latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_duration_ms: float
    prompt_version: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RagAnswer(BaseModel):
    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    sufficient_context: bool
    warnings: list[str] = Field(default_factory=list)
    diagnostics: RagDiagnostics
