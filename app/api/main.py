"""FastAPI application entry point (Milestone 7).

Thin app factory + route registration only -- no retrieval, prompt,
model-provider, vector-store, or workflow-stage logic lives here or in
any route handler. Business logic lives in `app.api.services`, which
itself only calls the unchanged Milestone 1-6 entry points
(`RagService`, `AdvisorOrchestrator`, `AdvisorRouter`, `WorkflowEngine`,
the evaluators). Run via `python -m app.api` or
`uvicorn app.api.main:app --reload`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.middleware.request_context import RequestContextMiddleware
from app.api.routes import advisors, auth, health, knowledge, query, workflows
from app.audit.store import AuditStore
from app.auth.users import load_users
from app.config.settings import (
    ApiSettings,
    AuthSettings,
    IngestionSettings,
    RagSettings,
    RetrievalSettings,
    RouterSettings,
    WorkflowSettings,
)
from app.rag.pipeline import build_default_rag_service
from app.workflows.engine import WorkflowEngine
from app.workflows.store import WorkflowStore

APP_VERSION = "0.7.0"
API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Loads process-wide singletons once, at startup, onto `app.state` --
    never reconstructed per-request. `app.auth.users.load_users` raises
    `UserDirectoryError` (fail-fast startup validation) if the configured
    users file is missing/malformed. More singletons (`WorkflowEngine`,
    stores) are added here in later steps."""
    auth_settings = AuthSettings.from_env()
    app.state.users = load_users(auth_settings.users_file)

    api_settings = ApiSettings.from_env()
    app.state.audit_store = AuditStore(api_settings.audit_log_dir)

    rag_settings = RagSettings.from_env()
    retrieval_settings = RetrievalSettings.from_env()
    router_settings = RouterSettings.from_env()
    ingestion_settings = IngestionSettings.from_env()

    app.state.rag_settings = rag_settings
    app.state.retrieval_settings = retrieval_settings
    app.state.router_settings = router_settings
    app.state.ingestion_settings = ingestion_settings
    app.state.rag_service = build_default_rag_service(rag_settings, retrieval_settings)

    workflow_settings = WorkflowSettings.from_env()
    app.state.workflow_settings = workflow_settings
    app.state.workflow_engine = WorkflowEngine(
        app.state.rag_service, WorkflowStore(workflow_settings.workflow_store_dir), rag_settings,
    )

    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Northstar Enterprise AI Transformation Platform",
        description=(
            "Internal reference platform providing grounded engineering and AI-transformation "
            "guidance over Northstar Lending Corporation's (fictional) internal knowledge base. "
            "Human-controlled, non-autonomous, and not authorized to execute production actions."
        ),
        version=APP_VERSION,
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(query.router, prefix=API_PREFIX)
    app.include_router(advisors.router, prefix=API_PREFIX)
    app.include_router(knowledge.router, prefix=API_PREFIX)
    app.include_router(workflows.router, prefix=API_PREFIX)

    return app


app = create_app()
