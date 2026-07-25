"""Background operations endpoints (Milestone 8).

Viewing an operation's status is viewer-level (visibility, same tier as
knowledge listing); starting one is administrator-level, matching the
synchronous `POST /knowledge/rebuild` it wraps -- same confirmation
phrase requirement, same audit action name family.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.dependencies.services import (
    get_audit_store,
    get_ingestion_settings,
    get_lock_registry,
    get_operation_runner,
    get_retrieval_settings,
)
from app.api.errors import ApiError, ErrorCode
from app.api.schemas.common import DEFAULT_PAGE_SIZE, PaginatedResponse, paginate_slice, validate_pagination
from app.api.schemas.knowledge import RebuildRequest
from app.api.schemas.operations import OperationOut, build_operation_out
from app.api.services.operations_service import get_operation, list_operations, start_knowledge_rebuild
from app.audit.logger import AuditContext, record_from_context
from app.audit.store import AuditStore
from app.auth.dependencies import require_role
from app.auth.roles import Role
from app.auth.users import User
from app.config.settings import IngestionSettings, RetrievalSettings
from app.operations.background import OperationRunner
from app.resilience.concurrency import LockRegistry

router = APIRouter()


@router.get(
    "/operations", summary="List background operations", tags=["Operations"],
    response_model=PaginatedResponse[OperationOut],
)
def list_operations_route(
    operation_type: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
    runner: OperationRunner = Depends(get_operation_runner),
    _user: User = Depends(require_role(Role.VIEWER)),
) -> PaginatedResponse[OperationOut]:
    page, page_size = validate_pagination(page, page_size)
    operations = list_operations(runner, operation_type=operation_type, status=status_filter)
    page_items, total_items, total_pages = paginate_slice(operations, page, page_size)
    return PaginatedResponse[OperationOut](
        items=[build_operation_out(op) for op in page_items],
        page=page, page_size=page_size, total_items=total_items, total_pages=total_pages,
    )


@router.get(
    "/operations/{operation_id}", summary="Get a background operation's status", tags=["Operations"],
    response_model=OperationOut,
)
def get_operation_route(
    operation_id: str, runner: OperationRunner = Depends(get_operation_runner),
    _user: User = Depends(require_role(Role.VIEWER)),
) -> OperationOut:
    return build_operation_out(get_operation(runner, operation_id))


@router.post(
    "/operations/rebuild", summary="Start a full vector-index rebuild in the background",
    tags=["Operations"], response_model=OperationOut, status_code=status.HTTP_202_ACCEPTED,
)
def start_rebuild_operation_route(
    body: RebuildRequest,
    request: Request,
    ingestion_settings: IngestionSettings = Depends(get_ingestion_settings),
    retrieval_settings: RetrievalSettings = Depends(get_retrieval_settings),
    audit_store: AuditStore = Depends(get_audit_store),
    lock_registry: LockRegistry = Depends(get_lock_registry),
    runner: OperationRunner = Depends(get_operation_runner),
    user: User = Depends(require_role(Role.ADMINISTRATOR)),
) -> OperationOut:
    if body.confirmation != "REBUILD":
        raise ApiError(400, ErrorCode.VALIDATION_ERROR, "Type REBUILD (exact case) to confirm a full rebuild.")

    operation_id = start_knowledge_rebuild(
        runner, lock_registry, ingestion_settings, retrieval_settings, created_by=user.username,
    )
    request_id = getattr(request.state, "request_id", None)
    record_from_context(
        AuditContext(store=audit_store, actor=user.username, role=user.role.value, request_id=request_id),
        action="vector_index_rebuild_started", resource_type="operation", resource_id=operation_id,
    )
    return build_operation_out(get_operation(runner, operation_id))
