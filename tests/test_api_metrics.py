"""Tests for the `/metrics` endpoint and its wiring into the
application-service layer (Milestone 8). Metrics live in one
process-wide `CollectorRegistry` shared across the whole pytest
session -- Counters only ever go up, so every assertion here compares a
*before/after delta*, never an absolute value, to stay order-independent
regardless of what other tests already incremented.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.services import (
    get_ingestion_settings,
    get_rag_service,
    get_rag_settings,
    get_retrieval_settings,
    get_workflow_engine,
)
from app.api.main import create_app
from app.config.settings import IngestionSettings, RagSettings, RetrievalSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.ingestion.pipeline import IngestionPipeline
from app.rag.context_builder import ContextBuilder
from app.rag.pipeline import RagService
from app.rag.retriever import Retriever
from app.services.llm_service import FakeModelProvider
from app.telemetry.metrics import REGISTRY
from app.workflows.engine import WorkflowEngine
from app.workflows.store import WorkflowStore

_ARCHITECTURE_REVIEW_INPUTS = {
    "solution_name": "Loan Payment Notification Platform",
    "business_objective": "Send real-time payment confirmation notifications",
    "architecture_description": "A Kubernetes-hosted synchronous microservice calling five downstream systems.",
    "data_classification": "Confidential",
    "deployment_target": "Kubernetes",
    "expected_volume": "2 million notifications per day",
    "known_constraints": ["Must use the existing enterprise API gateway"],
}


def _rag_settings(**overrides):
    defaults = dict(
        llm_provider="fake", llm_model="fake-echo-v1", llm_api_key=None,
        llm_temperature=0.0, llm_max_output_tokens=1024, llm_timeout_seconds=30.0,
        context_max_characters=6000, context_max_chunks=6, context_min_score=0.0,
        max_question_length=2000, insufficient_context_min_results=1, insufficient_context_min_score=0.0,
    )
    defaults.update(overrides)
    return RagSettings(**defaults)


def _seed_kb(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    for filename, (document_id, title) in {
        "11_Architecture_Principles.md": ("NLC-ENG-002", "Architecture Principles"),
        "12_AI_Engineering_Standards.md": ("NLC-ENG-003", "AI Engineering Standards"),
        "13_DevSecOps_Standards.md": ("NLC-ENG-004", "DevSecOps Standards"),
        "14_Testing_Strategy.md": ("NLC-ENG-005", "Testing Strategy"),
    }.items():
        (kb_dir / filename).write_text(
            f"---\ndocument_id: {document_id}\ntitle: {title}\n---\n\n"
            f"# {title}\n\n## Standards\n\n" + (f"{title} defines the relevant standard. " * 20),
            encoding="utf-8",
        )
    return kb_dir


def _ingestion_settings(tmp_path, kb_dir):
    return IngestionSettings(
        knowledge_base_dirs=(kb_dir,), supported_extensions=(".md",),
        chunk_size=500, chunk_overlap=50, log_level="INFO", output_dir=tmp_path / "processed",
    )


def _retrieval_settings(tmp_path):
    return RetrievalSettings(
        embedding_provider="local", embedding_model="local-hashing-v1", embedding_dimensions=128,
        vector_store_dir=tmp_path / "vstore", retrieval_top_k=10, openai_api_key=None,
    )


def _build_service_and_engine(tmp_path):
    kb_dir = _seed_kb(tmp_path)
    ingestion_settings = _ingestion_settings(tmp_path, kb_dir)
    retrieval_settings = _retrieval_settings(tmp_path)
    pipeline = IngestionPipeline(settings=ingestion_settings)
    provider = LocalHashingEmbeddingProvider(dimensions=128)
    vector_store = LocalVectorStore(retrieval_settings.vector_store_dir)
    Indexer(provider, vector_store).index_from_pipeline(pipeline)
    retriever = Retriever(provider, vector_store)
    context_builder = ContextBuilder(
        max_characters=6000, max_chunks=6, min_score=0.0, insufficient_min_results=1, insufficient_min_score=0.0,
    )
    service = RagService(retriever, context_builder, FakeModelProvider(), _rag_settings(), default_top_k=10)
    store = WorkflowStore(tmp_path / "workflow_store")
    return service, WorkflowEngine(service, store, _rag_settings()), ingestion_settings, retrieval_settings


@pytest.fixture
def users_file(tmp_path, monkeypatch):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps([
            {"api_key": "viewer-key", "username": "v", "role": "viewer"},
            {"api_key": "engineer-key", "username": "e", "role": "engineer"},
            {"api_key": "reviewer-key", "username": "r", "role": "reviewer"},
            {"api_key": "admin-key", "username": "a", "role": "administrator"},
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_USERS_FILE", str(path))
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit_log"))
    return path


@pytest.fixture
def client(users_file, tmp_path):
    service, workflow_engine, ingestion_settings, retrieval_settings = _build_service_and_engine(tmp_path)
    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_rag_settings] = lambda: _rag_settings()
    app.dependency_overrides[get_workflow_engine] = lambda: workflow_engine
    app.dependency_overrides[get_ingestion_settings] = lambda: ingestion_settings
    app.dependency_overrides[get_retrieval_settings] = lambda: retrieval_settings

    with TestClient(app) as test_client:
        yield test_client


VIEWER_HEADERS = {"X-API-Key": "viewer-key"}
ENGINEER_HEADERS = {"X-API-Key": "engineer-key"}
REVIEWER_HEADERS = {"X-API-Key": "reviewer-key"}


def _sample(name, labels=None):
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_metrics_endpoint_is_reachable_without_auth(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "api_requests_total" in response.text


def test_a_query_increments_rag_and_advisor_metrics(client):
    before = _sample("rag_questions_total", {"advisor": "testing", "mode": "manual", "sufficient_context": "true"})

    client.post(
        "/api/v1/query", json={"question": "What testing evidence is required?", "advisor": "testing"},
        headers=VIEWER_HEADERS,
    )

    after = _sample("rag_questions_total", {"advisor": "testing", "mode": "manual", "sufficient_context": "true"})
    assert after == before + 1


def test_a_completed_workflow_increments_lifecycle_and_stage_metrics(client):
    before_completed = _sample("workflows_completed_total", {"workflow_id": "architecture_review"})
    before_started = _sample("workflows_started_total", {"workflow_id": "architecture_review"})

    execute_response = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=ENGINEER_HEADERS,
    )
    execution_id = execute_response.json()["execution_id"]
    assert execute_response.json()["status"] == "awaiting_approval"

    assert _sample("workflows_started_total", {"workflow_id": "architecture_review"}) == before_started + 1
    # Not completed yet -- still paused for approval.
    assert _sample("workflows_completed_total", {"workflow_id": "architecture_review"}) == before_completed

    decide_response = client.post(
        f"/api/v1/approvals/{execution_id}/decide", json={"decision": "approve", "comments": "Looks good."},
        headers=REVIEWER_HEADERS,
    )
    assert decide_response.json()["status"] == "completed"

    assert _sample("workflows_completed_total", {"workflow_id": "architecture_review"}) == before_completed + 1
    assert _sample(
        "workflow_stage_duration_seconds_count",
        {"workflow_id": "architecture_review", "stage_id": "validate_architecture_input"},
    ) >= 1
    assert _sample("workflow_approval_wait_seconds_count") >= 1


def test_a_rejected_workflow_increments_cancelled_not_completed(client):
    execute_response = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=ENGINEER_HEADERS,
    )
    execution_id = execute_response.json()["execution_id"]

    before_cancelled = _sample("workflows_cancelled_total", {"workflow_id": "architecture_review"})

    client.post(
        f"/api/v1/approvals/{execution_id}/decide",
        json={"decision": "reject", "comments": "Not ready."}, headers=REVIEWER_HEADERS,
    )

    assert _sample("workflows_cancelled_total", {"workflow_id": "architecture_review"}) == before_cancelled + 1


def test_knowledge_index_updates_chunk_gauge(client):
    non_admin_response = client.post("/api/v1/knowledge/index", headers=ENGINEER_HEADERS)
    assert non_admin_response.status_code == 403  # index is administrator-only, not engineer

    admin_response = client.post("/api/v1/knowledge/index", headers={"X-API-Key": "admin-key"})
    assert admin_response.status_code == 200
    total_chunks = admin_response.json()["total"]

    assert _sample("knowledge_chunks_indexed") == total_chunks
    assert _sample("knowledge_indexing_duration_seconds_count", {"operation": "index"}) >= 1
