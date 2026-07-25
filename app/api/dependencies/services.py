"""Dependency-injection accessors for process-wide singletons (Milestone 7).

Every singleton (`RagService`, settings objects, and -- added in later
steps -- `WorkflowEngine`/stores) is built exactly once, at FastAPI
startup (see the `lifespan` in `app.api.main`), and stored on
`request.app.state`. Using `Depends()`-based accessors here (rather than
importing module-level globals) lets tests override them via FastAPI's
own `app.dependency_overrides`, injecting a `FakeModelProvider`-backed
service per test instead of monkeypatching.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Request

from app.audit.store import AuditStore
from app.config.feature_flags import FeatureFlagSettings
from app.config.settings import (
    IngestionSettings,
    RagSettings,
    RetrievalSettings,
    RouterSettings,
    WorkflowSettings,
)
from app.evaluation.run_store import EvaluationRunStore
from app.operations.background import OperationRunner
from app.rag.pipeline import RagService
from app.resilience.concurrency import LockRegistry
from app.resilience.idempotency import IdempotencyStore
from app.telemetry.cost_tracker import CostTracker
from app.workflows.engine import WorkflowEngine


def get_rag_service(request: Request) -> RagService:
    return request.app.state.rag_service


def get_workflow_engine(request: Request) -> WorkflowEngine:
    return request.app.state.workflow_engine


def get_workflow_settings(request: Request) -> WorkflowSettings:
    return request.app.state.workflow_settings


def get_evaluation_run_store(request: Request) -> EvaluationRunStore:
    return request.app.state.evaluation_run_store


def get_started_at(request: Request) -> datetime:
    return request.app.state.started_at


def get_lock_registry(request: Request) -> LockRegistry:
    return request.app.state.lock_registry


def get_idempotency_store(request: Request) -> IdempotencyStore:
    return request.app.state.idempotency_store


def get_operation_runner(request: Request) -> OperationRunner:
    return request.app.state.operation_runner


def get_feature_flags(request: Request) -> FeatureFlagSettings:
    return request.app.state.feature_flags


def get_cost_tracker(request: Request) -> CostTracker:
    return request.app.state.cost_tracker


def get_audit_store(request: Request) -> AuditStore:
    return request.app.state.audit_store


def get_ingestion_settings(request: Request) -> IngestionSettings:
    return request.app.state.ingestion_settings


def get_rag_settings(request: Request) -> RagSettings:
    return request.app.state.rag_settings


def get_retrieval_settings(request: Request) -> RetrievalSettings:
    return request.app.state.retrieval_settings


def get_router_settings(request: Request) -> RouterSettings:
    return request.app.state.router_settings
