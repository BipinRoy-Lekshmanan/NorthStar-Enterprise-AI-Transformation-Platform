"""Tests for `POST /api/v1/query` (Milestone 7) -- manual advisor
selection, automatic routing, filter/routing_mode validation, and RBAC.
Real `RagService`/`AdvisorOrchestrator`/`AdvisorRouter` (Milestones 1-3,
5, unchanged) built against a small fixture KB with `FakeModelProvider`
-- no network, no API key, no dependency on the real (large) knowledge
base or its indexed vector store.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.services import get_rag_service, get_rag_settings, get_router_settings
from app.api.main import create_app
from app.config.settings import IngestionSettings, RagSettings, RouterSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.ingestion.pipeline import IngestionPipeline
from app.rag.context_builder import ContextBuilder
from app.rag.pipeline import RagService
from app.rag.retriever import Retriever
from app.services.llm_service import FakeModelProvider

AUTH_HEADERS = {"X-API-Key": "viewer-key"}


def _rag_settings(**overrides):
    defaults = dict(
        llm_provider="fake", llm_model="fake-echo-v1", llm_api_key=None,
        llm_temperature=0.0, llm_max_output_tokens=1024, llm_timeout_seconds=30.0,
        context_max_characters=6000, context_max_chunks=6, context_min_score=0.0,
        max_question_length=2000, insufficient_context_min_results=1, insufficient_context_min_score=0.0,
    )
    defaults.update(overrides)
    return RagSettings(**defaults)


def _router_settings(**overrides):
    defaults = dict(
        router_retrieval_top_k=12, router_min_confidence=0.15,
        router_supporting_min_ratio=0.4, router_max_supporting_advisors=2,
        router_retrieval_weight=0.6, router_keyword_weight=0.4,
    )
    defaults.update(overrides)
    return RouterSettings(**defaults)


def _seed_kb(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "14_Testing_Strategy.md").write_text(
        "---\ndocument_id: NLC-ENG-005\ntitle: Testing Strategy\n---\n\n# Testing Strategy\n\n## Coverage\n\n"
        + ("Unit and integration test coverage is required before every release. " * 15),
        encoding="utf-8",
    )
    (kb_dir / "15_Release_Management.md").write_text(
        "---\ndocument_id: NLC-ENG-006\ntitle: Release Management\n---\n\n# Release Management\n\n## Canary\n\n"
        + ("Canary deployment and rollback procedures govern every production release. " * 15),
        encoding="utf-8",
    )
    return kb_dir


def _build_service(tmp_path):
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
    return RagService(retriever, context_builder, FakeModelProvider(), _rag_settings(), default_top_k=10)


@pytest.fixture
def users_file(tmp_path, monkeypatch):
    path = tmp_path / "users.json"
    path.write_text(json.dumps([{"api_key": "viewer-key", "username": "v", "role": "viewer"}]), encoding="utf-8")
    monkeypatch.setenv("AUTH_USERS_FILE", str(path))
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit_log"))
    return path


@pytest.fixture
def client(users_file, tmp_path, monkeypatch):
    app = create_app()
    kb_root = tmp_path / "kb_root"
    kb_root.mkdir()
    service = _build_service(kb_root)
    # Restricted-document filtering (Milestone 8) resolves IngestionSettings
    # via app.state -- without this override every request would silently
    # re-run ingestion against the real enterprise_knowledge_base/ instead
    # of this test's own tmp_path fixture KB.
    monkeypatch.setenv("KNOWLEDGE_BASE_DIRS", str(kb_root / "kb"))

    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_rag_settings] = lambda: _rag_settings()
    app.dependency_overrides[get_router_settings] = lambda: _router_settings()

    with TestClient(app) as test_client:
        yield test_client


def test_manual_advisor_query_returns_grounded_answer(client):
    response = client.post(
        "/api/v1/query", json={"question": "What testing evidence is required?", "advisor": "testing"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sufficient_context"] is True
    assert body["routing"] is None
    assert body["citations"]
    assert all(c["source_file"] == "14_Testing_Strategy.md" for c in body["citations"])


def test_unknown_advisor_returns_404(client):
    response = client.post(
        "/api/v1/query", json={"question": "test", "advisor": "does-not-exist"}, headers=AUTH_HEADERS
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_auto_routing_returns_routing_info(client):
    response = client.post(
        "/api/v1/query",
        json={"question": "What testing evidence is required before every release?", "advisor": "auto"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["routing"] is not None
    assert body["routing"]["primary_advisor"]
    assert body["routing"]["mode"] == "auto"


def test_missing_api_key_is_rejected(client):
    response = client.post("/api/v1/query", json={"question": "test"})
    assert response.status_code == 401


def test_empty_question_is_rejected(client):
    response = client.post("/api/v1/query", json={"question": ""}, headers=AUTH_HEADERS)
    assert response.status_code == 422


def test_multiple_filter_values_rejected(client):
    response = client.post(
        "/api/v1/query", json={"question": "test", "filters": {"document_ids": ["a", "b"]}}, headers=AUTH_HEADERS
    )
    assert response.status_code == 422


def test_invalid_routing_mode_rejected(client):
    response = client.post("/api/v1/query", json={"question": "test", "routing_mode": "hybrid"}, headers=AUTH_HEADERS)
    assert response.status_code == 422


def test_manual_query_with_context_capture(client):
    response = client.post(
        "/api/v1/query",
        json={
            "question": "What testing evidence is required?", "advisor": "testing",
            "include_retrieved_context": True,
        },
        headers=AUTH_HEADERS,
    )
    body = response.json()
    assert body["retrieved_context"]


def test_manual_query_without_context_capture_returns_none(client):
    response = client.post(
        "/api/v1/query", json={"question": "What testing evidence is required?", "advisor": "testing"},
        headers=AUTH_HEADERS,
    )
    assert response.json()["retrieved_context"] is None


def test_auto_query_ignores_filters_with_warning(client):
    response = client.post(
        "/api/v1/query",
        json={"question": "test", "advisor": "auto", "filters": {"document_ids": ["NLC-ENG-005"]}},
        headers=AUTH_HEADERS,
    )
    body = response.json()
    assert any("ignored for automatic routing" in w for w in body["warnings"])


def test_response_includes_matching_request_id(client):
    response = client.post("/api/v1/query", json={"question": "test"}, headers=AUTH_HEADERS)
    assert response.json()["request_id"]
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_diagnostics_omitted_by_default(client):
    response = client.post(
        "/api/v1/query", json={"question": "What testing evidence is required?", "advisor": "testing"},
        headers=AUTH_HEADERS,
    )
    assert response.json()["diagnostics"] is None


def test_diagnostics_included_when_requested(client):
    response = client.post(
        "/api/v1/query",
        json={
            "question": "What testing evidence is required?", "advisor": "testing", "include_diagnostics": True,
        },
        headers=AUTH_HEADERS,
    )
    assert response.json()["diagnostics"] is not None


def test_successful_query_records_an_audit_event(client, tmp_path):
    from app.audit.store import AuditStore

    client.post(
        "/api/v1/query", json={"question": "What testing evidence is required?", "advisor": "testing"},
        headers=AUTH_HEADERS,
    )

    store = AuditStore.from_env()
    events = store.list_events()
    assert len(events) == 1
    assert events[0].actor == "v"
    assert events[0].role == "viewer"
    assert events[0].action == "grounded_question_asked"
    assert events[0].resource_id == "testing"
    assert events[0].request_id  # correlates with X-Request-ID


def test_markdown_format_returns_a_markdown_document(client):
    response = client.post(
        "/api/v1/query?format=markdown",
        json={"question": "What testing evidence is required?", "advisor": "testing"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text.startswith("# Grounded Query Answer")
    assert "What testing evidence is required?" in response.text
    assert "Northstar Lending Corporation is a fictional company" in response.text


def test_json_is_still_the_default_format(client):
    response = client.post(
        "/api/v1/query", json={"question": "What testing evidence is required?", "advisor": "testing"},
        headers=AUTH_HEADERS,
    )
    assert response.headers["content-type"].startswith("application/json")


def test_invalid_format_value_returns_422(client):
    response = client.post(
        "/api/v1/query?format=pdf", json={"question": "What testing evidence is required?", "advisor": "testing"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422
