"""Tests for platform diagnostic endpoints (Milestone 7): detailed
health (viewer-level, exercises a real retrieval call) and the audit
log view (administrator-level). Uses a tmp_path fixture KB -- never
the real one.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.services import get_rag_service, get_rag_settings
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


def _rag_settings(**overrides):
    defaults = dict(
        llm_provider="fake", llm_model="fake-echo-v1", llm_api_key=None,
        llm_temperature=0.0, llm_max_output_tokens=1024, llm_timeout_seconds=30.0,
        context_max_characters=6000, context_max_chunks=6, context_min_score=0.0,
        max_question_length=2000, insufficient_context_min_results=1, insufficient_context_min_score=0.0,
    )
    defaults.update(overrides)
    return RagSettings(**defaults)


def _build_service(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "14_Testing_Strategy.md").write_text(
        "---\ndocument_id: NLC-ENG-005\ntitle: Testing Strategy\n---\n\n"
        "# Testing Strategy\n\n## Coverage\n\n" + ("Unit and integration test coverage is required. " * 15),
        encoding="utf-8",
    )
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
    return RagService(retriever, context_builder, FakeModelProvider(), _rag_settings(), default_top_k=10)


@pytest.fixture
def users_file(tmp_path, monkeypatch):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps([
            {"api_key": "viewer-key", "username": "v", "role": "viewer"},
            {"api_key": "admin-key", "username": "a", "role": "administrator"},
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_USERS_FILE", str(path))
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit_log"))
    return path


@pytest.fixture
def client(users_file, tmp_path):
    service = _build_service(tmp_path)
    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_rag_settings] = lambda: _rag_settings()

    with TestClient(app) as test_client:
        yield test_client


VIEWER_HEADERS = {"X-API-Key": "viewer-key"}
ADMIN_HEADERS = {"X-API-Key": "admin-key"}


def test_health_detail_reports_ok_status(client):
    response = client.get("/api/v1/platform/health", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"]["retrieval_pipeline"] == "ok"
    assert body["advisor_count"] == 10
    assert body["workflow_count"] == 5
    assert body["uptime_seconds"] >= 0


def test_health_detail_requires_authentication(client):
    response = client.get("/api/v1/platform/health")
    assert response.status_code == 401


def test_viewer_cannot_view_audit_log(client):
    response = client.get("/api/v1/platform/audit", headers=VIEWER_HEADERS)
    assert response.status_code == 403


def test_administrator_can_view_audit_log(client):
    # Generate at least one audit event first.
    client.get("/api/v1/auth/me", headers=VIEWER_HEADERS)
    client.post(
        "/api/v1/query", json={"question": "What testing evidence is required?", "advisor": "testing"},
        headers=VIEWER_HEADERS,
    )
    response = client.get("/api/v1/platform/audit", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    events = response.json()
    assert events
    assert events[0]["action"] == "grounded_question_asked"


def test_audit_log_respects_limit(client):
    for _ in range(3):
        client.post(
            "/api/v1/query", json={"question": "What testing evidence is required?", "advisor": "testing"},
            headers=VIEWER_HEADERS,
        )
    response = client.get("/api/v1/platform/audit?limit=1", headers=ADMIN_HEADERS)
    assert len(response.json()) == 1
