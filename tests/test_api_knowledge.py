"""Tests for knowledge management endpoints (Milestone 7): document
listing/filtering/pagination, detail, stats, search, and the
ingest/index/rebuild admin actions. Everything runs against a small
tmp_path fixture KB -- never the real (large) `enterprise_knowledge_base/`
or its real `vector_store/`, since ingest/index/rebuild here are
genuinely destructive/rewriting actions.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.services import (
    get_ingestion_settings,
    get_rag_service,
    get_rag_settings,
    get_retrieval_settings,
    get_router_settings,
)
from app.api.main import create_app
from app.config.settings import IngestionSettings, RagSettings, RetrievalSettings, RouterSettings
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


def _seed_kb(kb_dir):
    kb_dir.mkdir(exist_ok=True)
    (kb_dir / "14_Testing_Strategy.md").write_text(
        "---\ndocument_id: NLC-ENG-005\ntitle: Testing Strategy\nowner: QA Lead\nstatus: Approved\n"
        "classification: Internal\n---\n\n# Testing Strategy\n\n## Coverage\n\n"
        + ("Unit and integration test coverage is required before every release. " * 15),
        encoding="utf-8",
    )
    (kb_dir / "15_Release_Management.md").write_text(
        "---\ndocument_id: NLC-ENG-006\ntitle: Release Management\nowner: Release Manager\nstatus: Draft\n"
        "classification: Internal\n---\n\n# Release Management\n\n## Canary\n\n"
        + ("Canary deployment and rollback procedures govern every production release. " * 15),
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


def _build_indexed_service(tmp_path, kb_dir, ingestion_settings, retrieval_settings):
    pipeline = IngestionPipeline(settings=ingestion_settings)
    provider = LocalHashingEmbeddingProvider(dimensions=128)
    vector_store = LocalVectorStore(retrieval_settings.vector_store_dir)
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
    kb_dir = _seed_kb(tmp_path / "kb")
    ingestion_settings = _ingestion_settings(tmp_path, kb_dir)
    retrieval_settings = _retrieval_settings(tmp_path)
    service = _build_indexed_service(tmp_path, kb_dir, ingestion_settings, retrieval_settings)

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_rag_settings] = lambda: _rag_settings()
    app.dependency_overrides[get_router_settings] = lambda: _router_settings()
    app.dependency_overrides[get_ingestion_settings] = lambda: ingestion_settings
    app.dependency_overrides[get_retrieval_settings] = lambda: retrieval_settings

    with TestClient(app) as test_client:
        yield test_client


VIEWER_HEADERS = {"X-API-Key": "viewer-key"}
ADMIN_HEADERS = {"X-API-Key": "admin-key"}


def test_list_documents_returns_both_seeded_documents(client):
    response = client.get("/api/v1/knowledge/documents", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 2
    titles = {item["title"] for item in body["items"]}
    assert titles == {"Testing Strategy", "Release Management"}


def test_list_documents_filters_by_status(client):
    response = client.get("/api/v1/knowledge/documents?status=Draft", headers=VIEWER_HEADERS)
    body = response.json()
    assert body["total_items"] == 1
    assert body["items"][0]["title"] == "Release Management"


def test_list_documents_filters_by_owner_substring(client):
    response = client.get("/api/v1/knowledge/documents?owner=QA", headers=VIEWER_HEADERS)
    body = response.json()
    assert body["total_items"] == 1
    assert body["items"][0]["owner"] == "QA Lead"


def test_list_documents_pagination(client):
    response = client.get("/api/v1/knowledge/documents?page=1&page_size=1", headers=VIEWER_HEADERS)
    body = response.json()
    assert len(body["items"]) == 1
    assert body["total_items"] == 2
    assert body["total_pages"] == 2


def test_get_document_detail(client):
    response = client.get("/api/v1/knowledge/documents/NLC-ENG-005", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Testing Strategy"
    assert body["chunk_count"] > 0
    assert body["section_titles"]


def test_get_unknown_document_returns_404(client):
    response = client.get("/api/v1/knowledge/documents/DOES-NOT-EXIST", headers=VIEWER_HEADERS)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_knowledge_stats(client):
    response = client.get("/api/v1/knowledge/stats", headers=VIEWER_HEADERS)
    body = response.json()
    assert body["document_count"] == 2
    assert body["chunk_count"] > 0


def test_search_returns_scored_excerpts_not_full_text(client):
    response = client.post(
        "/api/v1/knowledge/search", json={"question": "What testing evidence is required?", "top_k": 5},
        headers=VIEWER_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["results"]
    for result in body["results"]:
        assert "score" in result
        assert len(result["excerpt"]) <= 243  # _EXCERPT_LENGTH + "..."


def test_search_with_include_full_text_returns_untruncated_chunks(client):
    response = client.post(
        "/api/v1/knowledge/search",
        json={"question": "What testing evidence is required?", "top_k": 5, "include_full_text": True},
        headers=VIEWER_HEADERS,
    )
    body = response.json()
    assert any(not result["excerpt"].endswith("...") for result in body["results"])


def test_viewer_cannot_run_ingestion(client):
    response = client.post("/api/v1/knowledge/ingest", headers=VIEWER_HEADERS)
    assert response.status_code == 403


def test_admin_can_run_ingestion(client):
    response = client.post("/api/v1/knowledge/ingest", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["documents_loaded"] == 2
    assert body["chunks_created"] > 0


def test_ingest_with_the_same_idempotency_key_does_not_repeat_side_effects(client):
    headers = {**ADMIN_HEADERS, "Idempotency-Key": "ingest-retry-1"}

    first = client.post("/api/v1/knowledge/ingest", headers=headers)
    second = client.post("/api/v1/knowledge/ingest", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_admin_can_run_incremental_index(client):
    response = client.post("/api/v1/knowledge/index", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    body = response.json()
    # Nothing changed since the fixture already indexed everything -- expect all unchanged.
    assert body["unchanged"] == body["total"]
    assert body["added"] == 0


def test_rebuild_requires_exact_confirmation_phrase(client):
    response = client.post("/api/v1/knowledge/rebuild", json={"confirmation": "yes please"}, headers=ADMIN_HEADERS)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_rebuild_with_correct_confirmation_reindexes_everything(client):
    response = client.post("/api/v1/knowledge/rebuild", json={"confirmation": "REBUILD"}, headers=ADMIN_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["added"] == body["total"]
    assert body["removed"] == 0  # nothing was removed from the KB, only re-added after deletion


def test_viewer_cannot_rebuild(client):
    response = client.post("/api/v1/knowledge/rebuild", json={"confirmation": "REBUILD"}, headers=VIEWER_HEADERS)
    assert response.status_code == 403


def test_knowledge_endpoints_require_authentication(client):
    response = client.get("/api/v1/knowledge/documents")
    assert response.status_code == 401
