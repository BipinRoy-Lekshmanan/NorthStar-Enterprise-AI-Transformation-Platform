"""Tests for advisor endpoints (Milestone 7): listing, detail, routing
preview, direct advisor query, and role enforcement. Real
`RagService`/`AdvisorRouter` (Milestones 1-3, 5, unchanged) built
against a small fixture KB with `FakeModelProvider` -- no network, no
API key, no dependency on the real (large) knowledge base.
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
    path.write_text(
        json.dumps([
            {"api_key": "viewer-key", "username": "v", "role": "viewer"},
            {"api_key": "engineer-key", "username": "e", "role": "engineer"},
        ]),
        encoding="utf-8",
    )
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


VIEWER_HEADERS = {"X-API-Key": "viewer-key"}
ENGINEER_HEADERS = {"X-API-Key": "engineer-key"}


def test_list_advisors_returns_all_ten(client):
    response = client.get("/api/v1/advisors", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 10
    ids = {a["advisor_id"] for a in body}
    assert "testing" in ids
    assert "security" in ids


def test_list_advisors_never_exposes_full_system_prompt(client):
    response = client.get("/api/v1/advisors", headers=VIEWER_HEADERS)
    body = response.json()
    for advisor in body:
        assert "persona" not in advisor
        assert "system_prompt" not in advisor
        assert "prompt_version" in advisor


def test_get_advisor_detail(client):
    response = client.get("/api/v1/advisors/testing", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["advisor_id"] == "testing"
    assert body["default_document_id"] == "NLC-ENG-005"
    assert body["expected_output_sections"]


def test_get_unknown_advisor_returns_404(client):
    response = client.get("/api/v1/advisors/does-not-exist", headers=VIEWER_HEADERS)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_route_only_does_not_require_engineer_role(client):
    response = client.post(
        "/api/v1/advisors/route", json={"question": "What testing evidence is required?"}, headers=VIEWER_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["primary_advisor"]
    assert "supporting_advisors" in body


def test_viewer_cannot_query_a_specific_advisor(client):
    response = client.post(
        "/api/v1/advisors/testing/query", json={"question": "What testing evidence is required?"},
        headers=VIEWER_HEADERS,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_engineer_can_query_a_specific_advisor(client):
    response = client.post(
        "/api/v1/advisors/testing/query", json={"question": "What testing evidence is required?"},
        headers=ENGINEER_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["citations"]
    assert body["routing"] is None  # manual advisor selection, not auto-routed


def test_advisor_query_with_unknown_advisor_returns_404(client):
    response = client.post(
        "/api/v1/advisors/does-not-exist/query", json={"question": "test"}, headers=ENGINEER_HEADERS
    )
    assert response.status_code == 404


def test_advisors_endpoints_require_authentication(client):
    response = client.get("/api/v1/advisors")
    assert response.status_code == 401
