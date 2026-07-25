"""Knowledge management endpoints (Milestone 7).

Listing/detail/stats/search are viewer-level ("search knowledge" is a
viewer permission); ingestion/indexing/rebuild are administrator-level
("run ingestion", "run indexing", "rebuild the vector index").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.dependencies.services import (
    get_audit_store,
    get_idempotency_store,
    get_ingestion_settings,
    get_lock_registry,
    get_rag_service,
    get_retrieval_settings,
)
from app.api.errors import ApiError, ErrorCode
from app.api.schemas.common import DEFAULT_PAGE_SIZE, PaginatedResponse, paginate_slice, validate_pagination
from app.api.schemas.knowledge import (
    DocumentOut,
    IndexSummaryOut,
    IngestionSummaryOut,
    KnowledgeStatsOut,
    RebuildRequest,
    SearchRequest,
    SearchResponse,
    build_document_out,
    build_search_result_out,
)
from app.api.services.idempotency_service import check_idempotency, save_idempotent_response
from app.api.services.knowledge_service import (
    DocumentFilter,
    build_catalog,
    filter_documents,
    get_document,
    knowledge_stats,
    run_full_rebuild,
    run_incremental_index,
    run_ingestion,
    search_knowledge,
)
from app.audit.logger import AuditContext, record_from_context
from app.audit.store import AuditStore
from app.auth.dependencies import require_role
from app.auth.roles import Role
from app.auth.users import User
from app.config.settings import IngestionSettings, RetrievalSettings
from app.rag.pipeline import RagService
from app.resilience.concurrency import LockRegistry
from app.resilience.idempotency import IdempotencyStore

router = APIRouter()


@router.get(
    "/knowledge/documents", summary="List indexed documents", tags=["Knowledge"],
    response_model=PaginatedResponse[DocumentOut],
)
def list_documents_route(
    title: str | None = None,
    document_id: str | None = None,
    source_path: str | None = None,
    status: str | None = None,
    owner: str | None = None,
    domain: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
    ingestion_settings: IngestionSettings = Depends(get_ingestion_settings),
    _user: User = Depends(require_role(Role.VIEWER)),
) -> PaginatedResponse[DocumentOut]:
    page, page_size = validate_pagination(page, page_size)
    filters = DocumentFilter(
        title=title, document_id=document_id, source_path=source_path, status=status, owner=owner, domain=domain,
    )
    documents = filter_documents(build_catalog(ingestion_settings), filters)
    page_items, total_items, total_pages = paginate_slice(documents, page, page_size)
    return PaginatedResponse[DocumentOut](
        items=[build_document_out(d) for d in page_items],
        page=page, page_size=page_size, total_items=total_items, total_pages=total_pages,
    )


@router.get(
    "/knowledge/documents/{document_id}", summary="Get document detail", tags=["Knowledge"],
    response_model=DocumentOut,
)
def get_document_route(
    document_id: str,
    ingestion_settings: IngestionSettings = Depends(get_ingestion_settings),
    _user: User = Depends(require_role(Role.VIEWER)),
) -> DocumentOut:
    return build_document_out(get_document(document_id, ingestion_settings))


@router.get(
    "/knowledge/stats", summary="Knowledge base statistics", tags=["Knowledge"], response_model=KnowledgeStatsOut,
)
def knowledge_stats_route(
    ingestion_settings: IngestionSettings = Depends(get_ingestion_settings),
    _user: User = Depends(require_role(Role.VIEWER)),
) -> KnowledgeStatsOut:
    return KnowledgeStatsOut(**knowledge_stats(ingestion_settings))


@router.post(
    "/knowledge/search", summary="Semantic search (no answer generation)", tags=["Knowledge"],
    response_model=SearchResponse,
)
def search_route(
    body: SearchRequest,
    service: RagService = Depends(get_rag_service),
    _user: User = Depends(require_role(Role.VIEWER)),
) -> SearchResponse:
    filters: dict[str, str] = {}
    if body.document_id:
        filters["document_id"] = body.document_id
    if body.source_file:
        filters["source_file"] = body.source_file

    response = search_knowledge(service.retriever, body.question, top_k=body.top_k, filters=filters)
    return SearchResponse(
        results=[build_search_result_out(result, body.include_full_text) for result in response.results],
        total_indexed_chunks=response.diagnostics.total_indexed_chunks,
    )


@router.post(
    "/knowledge/ingest", summary="Run knowledge ingestion", tags=["Knowledge"], response_model=IngestionSummaryOut,
)
def ingest_route(
    request: Request,
    ingestion_settings: IngestionSettings = Depends(get_ingestion_settings),
    audit_store: AuditStore = Depends(get_audit_store),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    user: User = Depends(require_role(Role.ADMINISTRATOR)),
) -> IngestionSummaryOut:
    cached = check_idempotency(request, idempotency_store, "knowledge_ingest", {})
    if cached is not None:
        return JSONResponse(status_code=cached.status_code, content=cached.body)

    summary = run_ingestion(ingestion_settings)
    request_id = getattr(request.state, "request_id", None)
    record_from_context(
        AuditContext(store=audit_store, actor=user.username, role=user.role.value, request_id=request_id),
        action="ingestion_run", resource_type="knowledge_base", metadata=summary,
    )
    result = IngestionSummaryOut(**summary)
    save_idempotent_response(request, idempotency_store, "knowledge_ingest", {}, 200, result.model_dump(mode="json"))
    return result


@router.post(
    "/knowledge/index", summary="Run incremental indexing", tags=["Knowledge"], response_model=IndexSummaryOut,
)
def index_route(
    request: Request,
    ingestion_settings: IngestionSettings = Depends(get_ingestion_settings),
    retrieval_settings: RetrievalSettings = Depends(get_retrieval_settings),
    audit_store: AuditStore = Depends(get_audit_store),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    user: User = Depends(require_role(Role.ADMINISTRATOR)),
) -> IndexSummaryOut:
    cached = check_idempotency(request, idempotency_store, "knowledge_index", {})
    if cached is not None:
        return JSONResponse(status_code=cached.status_code, content=cached.body)

    report = run_incremental_index(ingestion_settings, retrieval_settings)
    request_id = getattr(request.state, "request_id", None)
    record_from_context(
        AuditContext(store=audit_store, actor=user.username, role=user.role.value, request_id=request_id),
        action="indexing_run", resource_type="vector_store",
        metadata={"added": report.added, "removed": report.removed, "unchanged": report.unchanged, "total": report.total},
    )
    result = IndexSummaryOut(added=report.added, removed=report.removed, unchanged=report.unchanged, total=report.total)
    save_idempotent_response(request, idempotency_store, "knowledge_index", {}, 200, result.model_dump(mode="json"))
    return result


@router.post(
    "/knowledge/rebuild", summary="Full vector-index rebuild (requires confirmation)", tags=["Knowledge"],
    response_model=IndexSummaryOut,
)
def rebuild_route(
    body: RebuildRequest,
    request: Request,
    ingestion_settings: IngestionSettings = Depends(get_ingestion_settings),
    retrieval_settings: RetrievalSettings = Depends(get_retrieval_settings),
    audit_store: AuditStore = Depends(get_audit_store),
    lock_registry: LockRegistry = Depends(get_lock_registry),
    user: User = Depends(require_role(Role.ADMINISTRATOR)),
) -> IndexSummaryOut:
    if body.confirmation != "REBUILD":
        raise ApiError(400, ErrorCode.VALIDATION_ERROR, "Type REBUILD (exact case) to confirm a full rebuild.")

    report = run_full_rebuild(ingestion_settings, retrieval_settings, lock_registry=lock_registry)
    request_id = getattr(request.state, "request_id", None)
    record_from_context(
        AuditContext(store=audit_store, actor=user.username, role=user.role.value, request_id=request_id),
        action="vector_index_rebuilt", resource_type="vector_store",
        metadata={"added": report.added, "removed": report.removed, "unchanged": report.unchanged, "total": report.total},
    )
    return IndexSummaryOut(added=report.added, removed=report.removed, unchanged=report.unchanged, total=report.total)
