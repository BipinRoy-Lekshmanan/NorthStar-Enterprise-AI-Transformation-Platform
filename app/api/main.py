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
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.middleware.metrics import MetricsMiddleware
from app.api.middleware.rate_limit import RateLimitMiddleware
from app.api.middleware.request_context import RequestContextMiddleware
from app.api.middleware.request_size_limit import RequestSizeLimitMiddleware
from app.api.middleware.security_headers import SecurityHeadersMiddleware
from app.api.routes import (
    advisors,
    approvals,
    auth,
    evaluation,
    health,
    knowledge,
    metrics,
    operations,
    platform,
    query,
    workflows,
)
from app.api.version import API_PREFIX, APP_VERSION
from app.audit.store import AuditStore
from app.auth.users import load_users
from app.config.environment import current_environment
from app.config.settings import (
    ApiSettings,
    AuthSettings,
    DatabaseSettings,
    EvaluationSettings,
    IngestionSettings,
    RagSettings,
    RetrievalSettings,
    RouterSettings,
    TelemetrySettings,
    WorkflowSettings,
)
from app.db.engine import build_engine, build_session_factory, create_all
from app.evaluation.run_store import EvaluationRunStore
from app.operations.background import OperationRunner
from app.rag.pipeline import build_default_rag_service
from app.resilience.concurrency import LockRegistry
from app.resilience.idempotency import IdempotencyStore
from app.telemetry.tracing import configure_tracing
from app.workflows.engine import WorkflowEngine
from app.workflows.store import WorkflowStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Loads process-wide singletons once, at startup, onto `app.state` --
    never reconstructed per-request. `app.auth.users.load_users` raises
    `UserDirectoryError` (fail-fast startup validation) if the configured
    users file is missing/malformed. More singletons (`WorkflowEngine`,
    stores) are added here in later steps."""
    app.state.started_at = datetime.now(timezone.utc)
    app.state.lock_registry = LockRegistry()

    db_engine = build_engine(DatabaseSettings.from_env().database_url)
    # Safety net for dev/test environments that never ran `python -m
    # app.db upgrade` -- a no-op (checkfirst) if Alembic already created
    # the schema, so it never conflicts with real migrations.
    create_all(db_engine)
    db_session_factory = build_session_factory(db_engine)
    app.state.idempotency_store = IdempotencyStore(db_session_factory)
    app.state.audit_store = AuditStore(db_session_factory)
    app.state.operation_runner = OperationRunner(db_session_factory)

    telemetry_settings = TelemetrySettings.from_env()
    configure_tracing(
        enabled=telemetry_settings.tracing_enabled,
        environment=current_environment().value,
        otlp_endpoint=telemetry_settings.otlp_endpoint,
    )

    auth_settings = AuthSettings.from_env()
    app.state.users = load_users(auth_settings.users_file)

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

    evaluation_settings = EvaluationSettings.from_env()
    app.state.evaluation_run_store = EvaluationRunStore(evaluation_settings.evaluation_runs_dir)

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

    api_settings = ApiSettings.from_env()

    # Added in reverse-of-execution order (Starlette wraps middleware so the
    # last one added runs first): security headers wrap literally everything
    # (even a 429/413 rejected before routing gets them); then metrics (so
    # that rejection still counts); then CORS handles preflight OPTIONS;
    # then the rate limiter rejects abusive clients before the body is even
    # read; then the size limit; then request-id/timing.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=api_settings.max_upload_bytes)
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=api_settings.rate_limit_per_minute,
        category_limits=api_settings.rate_limit_category_overrides,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(api_settings.cors_allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    register_exception_handlers(app)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(query.router, prefix=API_PREFIX)
    app.include_router(advisors.router, prefix=API_PREFIX)
    app.include_router(knowledge.router, prefix=API_PREFIX)
    app.include_router(workflows.router, prefix=API_PREFIX)
    app.include_router(approvals.router, prefix=API_PREFIX)
    app.include_router(evaluation.router, prefix=API_PREFIX)
    app.include_router(operations.router, prefix=API_PREFIX)
    app.include_router(platform.router, prefix=API_PREFIX)
    app.include_router(metrics.router)  # unprefixed -- Prometheus's own scrape convention

    return app


app = create_app()
