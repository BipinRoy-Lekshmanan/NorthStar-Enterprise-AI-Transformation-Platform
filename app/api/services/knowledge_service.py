"""Knowledge management application service (Milestone 7).

Thin facade over Milestone 1 ingestion (`IngestionPipeline`) and
Milestone 2 indexing/retrieval (`Indexer`, `Retriever`) -- no ingestion,
chunking, embedding, or retrieval logic is reimplemented here.

The document catalog (list/detail) is built by re-running the ingestion
pipeline's discover -> load -> extract-metadata -> chunk steps with
`persist=False` (no disk writes). The knowledge base is small enough
(tens of files) that a single run is fast, but this is now called on
every list/detail/search/classification-check request (Milestone 8's
restricted-document filtering added several more call sites per
request) -- `build_catalog()` is cached for `_CATALOG_CACHE_TTL_SECONDS`
per distinct `IngestionSettings` (Milestone 8's `app.cache.TTLCache`,
keyed on the settings themselves since they're a hashable frozen
dataclass). Caching alone would silently reintroduce a staleness bug,
so `run_ingestion`/`run_incremental_index`/`run_full_rebuild` all
explicitly invalidate the cache after they mutate the knowledge base --
the catalog still always reflects the most recent mutation, it just
doesn't re-run the full pipeline for every read in between.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.auth.roles import Role, role_at_least
from app.cache.ttl_cache import TTLCache
from app.config.settings import IngestionSettings, RetrievalSettings
from app.embeddings.indexer import Indexer, IndexSyncReport, build_provider_and_store
from app.ingestion.pipeline import IngestionPipeline, IngestionResult
from app.models.chunk import Chunk
from app.models.query import RetrievalQuery
from app.models.response import RetrievalResponse
from app.rag.retriever import Retriever
from app.resilience.concurrency import ConcurrencyConflictError, LockRegistry
from app.telemetry.metrics import (
    knowledge_chunks_indexed,
    knowledge_documents_discovered,
    knowledge_indexing_duration_seconds,
    knowledge_ingestion_failures_total,
)

_CATALOG_CACHE_TTL_SECONDS = 30.0
_catalog_cache: TTLCache[list["DocumentSummary"]] = TTLCache(ttl_seconds=_CATALOG_CACHE_TTL_SECONDS)

# Milestone 8: data-classification guardrail. Neither `Chunk` nor
# `Citation` carry a classification of their own (Milestone 1's chunk
# model is intentionally unchanged by this milestone), so Restricted
# content is filtered by cross-referencing `document_id` against the
# catalog instead.
_RESTRICTED_CLASSIFICATION = "restricted"
RESTRICTED_MINIMUM_ROLE = Role.ADMINISTRATOR


class UnknownDocumentError(KeyError):
    """Raised when a document_id doesn't match any document in the knowledge base."""


@dataclass(frozen=True)
class DocumentSummary:
    document_id: str | None
    title: str | None
    source_file: str
    source_path: str
    domain: str
    owner: str | None
    status: str | None
    classification: str | None
    section_titles: list[str] = field(default_factory=list)
    chunk_count: int = 0


@dataclass(frozen=True)
class DocumentFilter:
    title: str | None = None
    document_id: str | None = None
    source_path: str | None = None
    status: str | None = None
    owner: str | None = None
    domain: str | None = None


def _domain_from_path(source_path: str) -> str:
    """The top-level knowledge-base folder (e.g. "04_Engineering") is the
    closest existing, non-fabricated proxy for "domain" -- there is no
    dedicated domain/category field in DocumentMetadata today."""
    normalized = source_path.replace("\\", "/")
    parts = normalized.split("/")
    return parts[0] if len(parts) > 1 else "(root)"


def build_catalog(ingestion_settings: IngestionSettings | None = None) -> list[DocumentSummary]:
    settings = ingestion_settings or IngestionSettings.from_env()
    return _catalog_cache.get_or_compute(settings, lambda: _build_catalog_uncached(settings))


def _build_catalog_uncached(settings: IngestionSettings) -> list[DocumentSummary]:
    pipeline = IngestionPipeline(settings=settings)
    result: IngestionResult = pipeline.run(persist=False)

    chunks_by_source: dict[str, list[Chunk]] = {}
    for chunk in result.chunks:
        chunks_by_source.setdefault(chunk.source_path, []).append(chunk)

    summaries: list[DocumentSummary] = []
    for document in result.documents:
        chunks = chunks_by_source.get(document.source_path, [])
        section_titles = list(dict.fromkeys(chunk.section_title for chunk in chunks if chunk.section_title))
        summaries.append(
            DocumentSummary(
                document_id=document.metadata.document_id,
                title=document.metadata.title,
                source_file=document.source_file,
                source_path=document.source_path,
                domain=_domain_from_path(document.source_path),
                owner=document.metadata.owner,
                status=document.metadata.status,
                classification=document.metadata.classification,
                section_titles=section_titles,
                chunk_count=len(chunks),
            )
        )
    return summaries


def filter_documents(documents: list[DocumentSummary], filters: DocumentFilter) -> list[DocumentSummary]:
    def _matches(doc: DocumentSummary) -> bool:
        if filters.title and (not doc.title or filters.title.lower() not in doc.title.lower()):
            return False
        if filters.document_id and doc.document_id != filters.document_id:
            return False
        if filters.source_path and filters.source_path.lower() not in doc.source_path.lower():
            return False
        if filters.status and (doc.status or "").lower() != filters.status.lower():
            return False
        if filters.owner and filters.owner.lower() not in (doc.owner or "").lower():
            return False
        if filters.domain and doc.domain.lower() != filters.domain.lower():
            return False
        return True

    return [doc for doc in documents if _matches(doc)]


def get_document(document_id: str, ingestion_settings: IngestionSettings | None = None) -> DocumentSummary:
    """Raises `UnknownDocumentError` (mapped to 404 by `app.api.errors`)
    for an unrecognized `document_id`."""
    for document in build_catalog(ingestion_settings):
        if document.document_id == document_id:
            return document
    raise UnknownDocumentError(f"Unknown document_id '{document_id}'.")


def is_restricted(classification: str | None) -> bool:
    return (classification or "").strip().lower() == _RESTRICTED_CLASSIFICATION


def exclude_restricted_documents(documents: list[DocumentSummary]) -> list[DocumentSummary]:
    return [document for document in documents if not is_restricted(document.classification)]


def restricted_document_ids(ingestion_settings: IngestionSettings | None = None) -> set[str]:
    """document_id set for every catalog document classified Restricted --
    the cross-reference `search_knowledge`/citation filtering use, since
    neither `Chunk` nor `Citation` carry a classification of their own."""
    return {
        document.document_id for document in build_catalog(ingestion_settings)
        if document.document_id is not None and is_restricted(document.classification)
    }


def restricted_ids_for_role(role: Role, ingestion_settings: IngestionSettings | None = None) -> set[str]:
    """Returns the empty set for a role privileged enough to see
    Restricted content, so callers can unconditionally pass the result
    into `filter_restricted_citations`/`search_knowledge`'s
    `exclude_document_ids` without an `if` at every call site."""
    if role_at_least(role, RESTRICTED_MINIMUM_ROLE):
        return set()
    return restricted_document_ids(ingestion_settings)


def filter_restricted_citations(citations: list, restricted_ids: set[str]) -> list:
    if not restricted_ids:
        return citations
    return [citation for citation in citations if citation.document_id not in restricted_ids]


def knowledge_stats(ingestion_settings: IngestionSettings | None = None) -> dict:
    catalog = build_catalog(ingestion_settings)
    return {
        "document_count": len(catalog),
        "chunk_count": sum(document.chunk_count for document in catalog),
        "domains": sorted({document.domain for document in catalog}),
    }


def run_ingestion(ingestion_settings: IngestionSettings | None = None) -> dict:
    settings = ingestion_settings or IngestionSettings.from_env()
    with knowledge_indexing_duration_seconds.labels(operation="ingest").time():
        result = IngestionPipeline(settings=settings).run(persist=True)
    summary = result.summary
    knowledge_documents_discovered.set(summary["files_discovered"])
    if summary["documents_failed"]:
        knowledge_ingestion_failures_total.inc(summary["documents_failed"])
    _catalog_cache.invalidate()
    return summary


def run_incremental_index(
    ingestion_settings: IngestionSettings | None = None, retrieval_settings: RetrievalSettings | None = None
) -> IndexSyncReport:
    retrieval_settings = retrieval_settings or RetrievalSettings.from_env()
    provider, store = build_provider_and_store(retrieval_settings)
    indexer = Indexer(provider, store)
    pipeline = IngestionPipeline(settings=ingestion_settings or IngestionSettings.from_env())
    with knowledge_indexing_duration_seconds.labels(operation="index").time():
        report = indexer.index_from_pipeline(pipeline)
    knowledge_chunks_indexed.set(report.total)
    _catalog_cache.invalidate()
    return report


_REBUILD_LOCK_NAME = "knowledge_rebuild"


def run_full_rebuild(
    ingestion_settings: IngestionSettings | None = None, retrieval_settings: RetrievalSettings | None = None,
    lock_registry: LockRegistry | None = None,
) -> IndexSyncReport:
    """Deletes every currently-indexed chunk, then re-indexes from
    scratch. The route layer is responsible for validating an explicit
    confirmation phrase before ever calling this -- once called, it
    always rebuilds unconditionally.

    `lock_registry` (when supplied) prevents a second, concurrent
    rebuild from starting while one is already in progress -- two
    concurrent rebuilds racing to delete/re-index the same vector store
    would corrupt it, not just waste work."""
    def _do_rebuild() -> IndexSyncReport:
        settings = retrieval_settings or RetrievalSettings.from_env()
        provider, store = build_provider_and_store(settings)

        existing_ids = list(store.existing_ids())
        if existing_ids:
            store.delete(existing_ids)

        indexer = Indexer(provider, store)
        pipeline = IngestionPipeline(settings=ingestion_settings or IngestionSettings.from_env())
        with knowledge_indexing_duration_seconds.labels(operation="rebuild").time():
            report = indexer.index_from_pipeline(pipeline)
        knowledge_chunks_indexed.set(report.total)
        _catalog_cache.invalidate()
        return report

    if lock_registry is None:
        return _do_rebuild()

    # Deferred import: app.api.errors imports UnknownDocumentError from
    # this module, so a module-level import back here would be circular.
    from app.api.errors import ApiError, ErrorCode

    try:
        with lock_registry.acquire(_REBUILD_LOCK_NAME):
            return _do_rebuild()
    except ConcurrencyConflictError as exc:
        raise ApiError(
            409, ErrorCode.CONCURRENCY_CONFLICT, "A knowledge-base rebuild is already in progress.",
        ) from exc


def search_knowledge(
    retriever: Retriever, question: str, top_k: int = 10, filters: dict[str, str] | None = None,
    exclude_document_ids: set[str] | None = None,
) -> RetrievalResponse:
    """Semantic search only -- no answer generation, no citations, no
    advisor/prompt involvement. Reuses the exact Milestone 2 `Retriever`
    behind `RagService.retriever`.

    `exclude_document_ids` (typically `restricted_ids_for_role(...)`) is
    applied *after* retrieval -- results are still ranked over the full
    index, then Restricted matches are dropped from what's returned."""
    query = RetrievalQuery(text=question, top_k=top_k, filters=filters or {})
    response = retriever.retrieve(query)
    if exclude_document_ids:
        kept = [result for result in response.results if result.chunk.document_id not in exclude_document_ids]
        response = RetrievalResponse(results=kept, diagnostics=response.diagnostics)
    return response
