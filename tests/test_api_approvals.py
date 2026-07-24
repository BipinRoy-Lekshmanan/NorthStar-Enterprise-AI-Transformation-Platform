"""Tests for approval endpoints (Milestone 7): the pending queue,
required-comment enforcement on reject/request_changes, RBAC (viewer
can list, only reviewer+ can decide), and the not-awaiting-approval
precondition. Reuses the same real `architecture_review` fixture setup
as `tests/test_api_workflows.py` (always pauses for approval before
synthesis) against a tmp_path KB/workflow store -- never the real ones.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.services import get_rag_service, get_rag_settings, get_workflow_engine
from app.api.main import create_app
from app.config.settings import IngestionSettings, RagSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.ingestion.pipeline import IngestionPipeline
from app.rag.context_builder import ContextBuilder
from app.rag.pipeline import RagService
from app.rag.retriever import Retriever
from app.services.llm_service import FakeModelProvider
from app.workflows.engine import WorkflowEngine
from app.workflows.store import WorkflowStore

_DOCUMENTS = {
    "11_Architecture_Principles.md": ("NLC-ENG-002", "Architecture Principles"),
    "12_AI_Engineering_Standards.md": ("NLC-ENG-003", "AI Engineering Standards"),
    "13_DevSecOps_Standards.md": ("NLC-ENG-004", "DevSecOps Standards"),
}

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
    for filename, (document_id, title) in _DOCUMENTS.items():
        (kb_dir / filename).write_text(
            f"---\ndocument_id: {document_id}\ntitle: {title}\n---\n\n"
            f"# {title}\n\n## Standards\n\n"
            + (f"{title} defines the relevant Northstar standard for this area. " * 20),
            encoding="utf-8",
        )
    return kb_dir


def _build_service_and_engine(tmp_path):
    kb_dir = _seed_kb(tmp_path)
    ingestion_settings = IngestionSettings(
        knowledge_base_dirs=(kb_dir,), supported_extensions=(".md",),
        chunk_size=500, chunk_overlap=50, log_level="INFO", output_dir=tmp_path / "processed",
    )
    pipeline = IngestionPipeline(settings=ingestion_settings)
    provider = LocalHashingEmbeddingProvider(dimensions=128)
    vector_store = LocalVectorStore(tmp_path / "vstore")
    Indexer(provider, vector_store).index_from_pipeline(pipeline)
    retriever = Retriever(provider, vector_store)
    context_builder = ContextBuilder(
        max_characters=6000, max_chunks=6, min_score=0.0, insufficient_min_results=1, insufficient_min_score=0.0,
    )
    service = RagService(retriever, context_builder, FakeModelProvider(), _rag_settings(), default_top_k=10)
    store = WorkflowStore(tmp_path / "workflow_store")
    return service, WorkflowEngine(service, store, _rag_settings())


@pytest.fixture
def users_file(tmp_path, monkeypatch):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps([
            {"api_key": "viewer-key", "username": "v", "role": "viewer"},
            {"api_key": "engineer-key", "username": "e", "role": "engineer"},
            {"api_key": "reviewer-key", "username": "r", "role": "reviewer"},
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_USERS_FILE", str(path))
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit_log"))
    return path


@pytest.fixture
def service_and_engine(tmp_path):
    return _build_service_and_engine(tmp_path)


@pytest.fixture
def client(users_file, service_and_engine):
    service, workflow_engine = service_and_engine
    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_rag_settings] = lambda: _rag_settings()
    app.dependency_overrides[get_workflow_engine] = lambda: workflow_engine

    with TestClient(app) as test_client:
        yield test_client


VIEWER_HEADERS = {"X-API-Key": "viewer-key"}
ENGINEER_HEADERS = {"X-API-Key": "engineer-key"}
REVIEWER_HEADERS = {"X-API-Key": "reviewer-key"}


def _execute_and_pause(client) -> str:
    response = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=ENGINEER_HEADERS,
    )
    assert response.json()["status"] == "awaiting_approval"
    return response.json()["execution_id"]


def test_pending_approvals_starts_empty(client):
    response = client.get("/api/v1/approvals", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    assert response.json() == []


def test_pending_approvals_lists_a_paused_execution(client):
    execution_id = _execute_and_pause(client)
    response = client.get("/api/v1/approvals", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["execution_id"] == execution_id


def test_viewer_cannot_decide(client):
    execution_id = _execute_and_pause(client)
    response = client.post(
        f"/api/v1/approvals/{execution_id}/decide", json={"decision": "approve"}, headers=VIEWER_HEADERS,
    )
    assert response.status_code == 403


def test_engineer_cannot_decide(client):
    execution_id = _execute_and_pause(client)
    response = client.post(
        f"/api/v1/approvals/{execution_id}/decide", json={"decision": "approve"}, headers=ENGINEER_HEADERS,
    )
    assert response.status_code == 403


def test_reject_without_comment_is_rejected_with_400(client):
    execution_id = _execute_and_pause(client)
    response = client.post(
        f"/api/v1/approvals/{execution_id}/decide", json={"decision": "reject"}, headers=REVIEWER_HEADERS,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_request_changes_without_comment_is_rejected_with_400(client):
    execution_id = _execute_and_pause(client)
    response = client.post(
        f"/api/v1/approvals/{execution_id}/decide", json={"decision": "request_changes"}, headers=REVIEWER_HEADERS,
    )
    assert response.status_code == 400


def test_reject_with_comment_succeeds(client):
    execution_id = _execute_and_pause(client)
    response = client.post(
        f"/api/v1/approvals/{execution_id}/decide",
        json={"decision": "reject", "comments": "Missing rollback evidence."}, headers=REVIEWER_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_approve_resumes_and_completes_the_execution(client):
    execution_id = _execute_and_pause(client)
    response = client.post(
        f"/api/v1/approvals/{execution_id}/decide", json={"decision": "approve", "comments": "Looks good."},
        headers=REVIEWER_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["citations"]


def test_deciding_an_already_decided_execution_returns_409(client):
    execution_id = _execute_and_pause(client)
    client.post(
        f"/api/v1/approvals/{execution_id}/decide", json={"decision": "approve"}, headers=REVIEWER_HEADERS,
    )
    response = client.post(
        f"/api/v1/approvals/{execution_id}/decide", json={"decision": "approve"}, headers=REVIEWER_HEADERS,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APPROVAL_ERROR"


def test_invalid_decision_value_returns_422(client):
    execution_id = _execute_and_pause(client)
    response = client.post(
        f"/api/v1/approvals/{execution_id}/decide", json={"decision": "maybe"}, headers=REVIEWER_HEADERS,
    )
    assert response.status_code == 422


def test_approvals_endpoints_require_authentication(client):
    response = client.get("/api/v1/approvals")
    assert response.status_code == 401
