"""Request/response schemas for the grounded query endpoint (Milestone 7).

`routing_mode` is accepted for schema compatibility but only `"auto"` is
a real, supported value -- this platform has exactly one deterministic
routing algorithm (Milestone 5), not multiple selectable modes. A
request naming any other mode is rejected with a clear validation error
rather than silently accepted.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.api.services.query_service import QueryResult


class QueryFiltersIn(BaseModel):
    document_ids: list[str] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)

    @field_validator("document_ids", "source_files")
    @classmethod
    def _at_most_one(cls, value: list[str]) -> list[str]:
        if len(value) > 1:
            raise ValueError(
                "Only a single value is supported per filter in this milestone (the underlying "
                "retrieval filters are exact-match, not set membership)."
            )
        return value


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    advisor: str = Field(default="auto", description="A specific advisor id, or 'auto' for automatic routing.")
    routing_mode: str = Field(
        default="auto",
        description="Only 'auto' is supported -- this platform implements one deterministic routing algorithm.",
    )
    max_supporting_advisors: int | None = Field(default=None, ge=0, le=5)
    filters: QueryFiltersIn = Field(default_factory=QueryFiltersIn)
    include_diagnostics: bool = False
    include_retrieved_context: bool = False

    @field_validator("routing_mode")
    @classmethod
    def _validate_routing_mode(cls, value: str) -> str:
        if value != "auto":
            raise ValueError(f"routing_mode must be 'auto' (the only mode this platform implements), got '{value}'.")
        return value


class CitationOut(BaseModel):
    source_id: str
    document_title: str | None
    document_id: str | None
    source_file: str
    section_title: str | None
    excerpt: str
    score: float


class RoutingOut(BaseModel):
    primary_advisor: str
    supporting_advisors: list[str]
    confidence: float
    rationale: str
    fallback_used: bool
    mode: str = "auto"


class RetrievedChunkOut(BaseModel):
    source_id: str
    text: str
    score: float


class QueryResponse(BaseModel):
    request_id: str | None
    question: str
    answer: str
    sufficient_context: bool
    routing: RoutingOut | None
    citations: list[CitationOut]
    warnings: list[str]
    conflicts: list[str]
    diagnostics: dict | None = None
    retrieved_context: list[RetrievedChunkOut] | None = None
    degraded: bool = False


def build_query_response(result: QueryResult, request_id: str | None) -> QueryResponse:
    routing = None
    if result.confidence is not None:
        routing = RoutingOut(
            primary_advisor=result.primary_advisor,
            supporting_advisors=result.supporting_advisors,
            confidence=result.confidence,
            rationale=result.routing_rationale or "",
            fallback_used=bool(result.fallback_used),
        )

    return QueryResponse(
        request_id=request_id,
        question=result.question,
        answer=result.answer,
        sufficient_context=result.sufficient_context,
        routing=routing,
        citations=[
            CitationOut(
                source_id=c.source_id, document_title=c.document_title, document_id=c.document_id,
                source_file=c.source_file, section_title=c.section_title, excerpt=c.excerpt, score=c.score,
            )
            for c in result.citations
        ],
        warnings=result.warnings,
        conflicts=result.conflicts,
        diagnostics=result.diagnostics,
        retrieved_context=(
            [RetrievedChunkOut(source_id=c.source_id, text=c.text, score=c.score) for c in result.retrieved_context]
            if result.retrieved_context is not None
            else None
        ),
        degraded=result.degraded,
    )
