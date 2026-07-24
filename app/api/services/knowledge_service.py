"""Knowledge management application service (Milestone 7).

Thin facade over Milestone 1 ingestion (`IngestionPipeline`) and
Milestone 2 indexing/retrieval (`Indexer`, `Retriever`) -- no ingestion,
chunking, embedding, or retrieval logic is reimplemented here.

The document catalog (list/detail) is built by re-running the ingestion
pipeline's discover -> load -> extract-metadata -> chunk steps with
`persist=False` (no disk writes) on every call. The knowledge base is
small enough (tens of files) that this is fast, and it sidesteps a
stale-cache invalidation problem entirely: the catalog always reflects
whatever `run_ingestion`/`run_incremental_index`/`run_full_rebuild` most
recently did, with no cache to remember to bust.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config.settings import IngestionSettings, RetrievalSettings
from app.embeddings.indexer import Indexer, IndexSyncReport, build_provider_and_store
from app.ingestion.pipeline import IngestionPipeline, IngestionResult
from app.models.chunk import Chunk
from app.models.query import RetrievalQuery
from app.models.response import RetrievalResponse
from app.rag.retriever import Retriever


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


def knowledge_stats(ingestion_settings: IngestionSettings | None = None) -> dict:
    catalog = build_catalog(ingestion_settings)
    return {
        "document_count": len(catalog),
        "chunk_count": sum(document.chunk_count for document in catalog),
        "domains": sorted({document.domain for document in catalog}),
    }


def run_ingestion(ingestion_settings: IngestionSettings | None = None) -> dict:
    settings = ingestion_settings or IngestionSettings.from_env()
    result = IngestionPipeline(settings=settings).run(persist=True)
    return result.summary


def run_incremental_index(
    ingestion_settings: IngestionSettings | None = None, retrieval_settings: RetrievalSettings | None = None
) -> IndexSyncReport:
    retrieval_settings = retrieval_settings or RetrievalSettings.from_env()
    provider, store = build_provider_and_store(retrieval_settings)
    indexer = Indexer(provider, store)
    pipeline = IngestionPipeline(settings=ingestion_settings or IngestionSettings.from_env())
    return indexer.index_from_pipeline(pipeline)


def run_full_rebuild(
    ingestion_settings: IngestionSettings | None = None, retrieval_settings: RetrievalSettings | None = None
) -> IndexSyncReport:
    """Deletes every currently-indexed chunk, then re-indexes from
    scratch. The route layer is responsible for validating an explicit
    confirmation phrase before ever calling this -- once called, it
    always rebuilds unconditionally."""
    retrieval_settings = retrieval_settings or RetrievalSettings.from_env()
    provider, store = build_provider_and_store(retrieval_settings)

    existing_ids = list(store.existing_ids())
    if existing_ids:
        store.delete(existing_ids)

    indexer = Indexer(provider, store)
    pipeline = IngestionPipeline(settings=ingestion_settings or IngestionSettings.from_env())
    return indexer.index_from_pipeline(pipeline)


def search_knowledge(
    retriever: Retriever, question: str, top_k: int = 10, filters: dict[str, str] | None = None
) -> RetrievalResponse:
    """Semantic search only -- no answer generation, no citations, no
    advisor/prompt involvement. Reuses the exact Milestone 2 `Retriever`
    behind `RagService.retriever`."""
    query = RetrievalQuery(text=question, top_k=top_k, filters=filters or {})
    return retriever.retrieve(query)
