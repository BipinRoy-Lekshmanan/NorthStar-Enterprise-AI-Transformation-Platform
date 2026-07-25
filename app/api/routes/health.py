"""Health endpoints (Milestone 7-8).

`/health` is a pure liveness check -- a static fact about the process
being up, no service call at all. `/health/ready` (Milestone 8) is a
real capability check delegated to `app.api.services.platform_service`,
deliberately unauthenticated (a Kubernetes readiness probe can't send
credentials) and returns 503 -- not just `ready: false` in the body --
when a dependency check fails, since that's what orchestrators actually
key their traffic-routing decision off of.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies.services import get_audit_store, get_rag_service
from app.api.schemas.platform import ReadinessOut
from app.api.services.platform_service import get_readiness
from app.audit.store import AuditStore
from app.rag.pipeline import RagService

router = APIRouter()


@router.get("/health", summary="Liveness check", tags=["Health"])
def health() -> dict:
    """The API process is running. Does not imply the platform is ready
    to answer questions -- see `/health/ready`."""
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness check", tags=["Health"], response_model=ReadinessOut)
def readiness_route(
    response: Response,
    service: RagService = Depends(get_rag_service),
    audit_store: AuditStore = Depends(get_audit_store),
) -> ReadinessOut:
    result = get_readiness(service, audit_store)
    if not result["ready"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessOut(**result)
