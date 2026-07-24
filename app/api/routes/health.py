"""Health endpoints (Milestone 7).

Pure route handlers only -- liveness is a static fact about the process
being up, so there is no service call here at all. Readiness (added in a
later step, once singletons exist) is a real capability check and is
delegated to `app.api.services.platform_service`.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health", summary="Liveness check", tags=["Health"])
def health() -> dict:
    """The API process is running. Does not imply the platform is ready
    to answer questions -- see `/health/readiness`."""
    return {"status": "ok"}
