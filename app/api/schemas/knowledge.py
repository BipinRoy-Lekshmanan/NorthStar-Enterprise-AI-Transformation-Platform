"""Request/response schemas for knowledge management endpoints (Milestone 7).

Never returns full raw document text by default -- only section titles
and chunk counts for the catalog, and truncated excerpts (not full
chunk text) for search results, unless `include_full_text` is
explicitly requested.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.api.services.knowledge_service import DocumentSummary
from app.models.response import RetrievalResult

_EXCERPT_LENGTH = 240


class DocumentOut(BaseModel):
    document_id: str | None
    title: str | None
    source_file: str
    source_path: str
    domain: str
    owner: str | None
    status: str | None
    classification: str | None
    section_titles: list[str]
    chunk_count: int


def build_document_out(document: DocumentSummary) -> DocumentOut:
    return DocumentOut(
        document_id=document.document_id,
        title=document.title,
        source_file=document.source_file,
        source_path=document.source_path,
        domain=document.domain,
        owner=document.owner,
        status=document.status,
        classification=document.classification,
        section_titles=document.section_titles,
        chunk_count=document.chunk_count,
    )


class KnowledgeStatsOut(BaseModel):
    document_count: int
    chunk_count: int
    domains: list[str]


class SearchRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=50)
    document_id: str | None = None
    source_file: str | None = None
    include_full_text: bool = False


class SearchResultOut(BaseModel):
    document_title: str | None
    document_id: str | None
    source_file: str
    source_path: str
    section_title: str | None
    score: float
    excerpt: str


def build_search_result_out(result: RetrievalResult, include_full_text: bool) -> SearchResultOut:
    text = result.chunk.text
    excerpt = text if (include_full_text or len(text) <= _EXCERPT_LENGTH) else text[:_EXCERPT_LENGTH].rstrip() + "..."
    return SearchResultOut(
        document_title=result.chunk.document_title,
        document_id=result.chunk.document_id,
        source_file=result.chunk.source_file,
        source_path=result.chunk.source_path,
        section_title=result.chunk.section_title,
        score=result.score,
        excerpt=excerpt,
    )


class SearchResponse(BaseModel):
    results: list[SearchResultOut]
    total_indexed_chunks: int


class IngestionSummaryOut(BaseModel):
    files_discovered: int
    documents_loaded: int
    documents_failed: int
    chunks_created: int


class IndexSummaryOut(BaseModel):
    added: int
    removed: int
    unchanged: int
    total: int


class RebuildRequest(BaseModel):
    confirmation: str = Field(..., description="Must be exactly 'REBUILD' to confirm a full rebuild.")
