"""Tests for the background operations API (Milestone 8): starting a
knowledge rebuild in the background, polling its status, and listing/
filtering operations. Same tmp_path fixture KB pattern as
`tests/test_api_knowledge.py` -- never the real (large) knowledge base.
"""

import json
import time

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
        "---\ndocument_id: NLC-ENG-005\ntitle: Testing Strategy\n---\n\n# Testing Strategy\n\n## Coverage\n\n"
        + ("Unit and integration test coverage is required before every release. " * 15),
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


def _wait_until_terminal(client, operation_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/operations/{operation_id}", headers=VIEWER_HEADERS)
        body = response.json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.02)
    raise TimeoutError(f"Operation {operation_id} did not reach a terminal status in time.")


def test_viewer_cannot_start_a_rebuild_operation(client):
    response = client.post("/api/v1/operations/rebuild", json={"confirmation": "REBUILD"}, headers=VIEWER_HEADERS)
    assert response.status_code == 403


def test_rebuild_requires_exact_confirmation_phrase(client):
    response = client.post("/api/v1/operations/rebuild", json={"confirmation": "yes please"}, headers=ADMIN_HEADERS)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_admin_can_start_a_rebuild_operation_and_poll_it_to_completion(client):
    response = client.post("/api/v1/operations/rebuild", json={"confirmation": "REBUILD"}, headers=ADMIN_HEADERS)

    assert response.status_code == 202
    body = response.json()
    assert body["operation_type"] == "knowledge_rebuild"
    assert body["status"] in ("pending", "running", "completed")
    assert body["created_by"] == "a"

    final = _wait_until_terminal(client, body["operation_id"])
    assert final["status"] == "completed"
    assert final["result"]["total"] > 0
    assert final["error_message"] is None


def test_get_unknown_operation_returns_404(client):
    response = client.get("/api/v1/operations/does-not-exist", headers=VIEWER_HEADERS)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_list_operations_includes_the_started_rebuild(client):
    started = client.post("/api/v1/operations/rebuild", json={"confirmation": "REBUILD"}, headers=ADMIN_HEADERS)
    operation_id = started.json()["operation_id"]
    _wait_until_terminal(client, operation_id)

    response = client.get("/api/v1/operations", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 1
    assert body["items"][0]["operation_id"] == operation_id


def test_list_operations_filters_by_type(client):
    started = client.post("/api/v1/operations/rebuild", json={"confirmation": "REBUILD"}, headers=ADMIN_HEADERS)
    _wait_until_terminal(client, started.json()["operation_id"])

    matching = client.get("/api/v1/operations?operation_type=knowledge_rebuild", headers=VIEWER_HEADERS)
    assert matching.json()["total_items"] == 1

    non_matching = client.get("/api/v1/operations?operation_type=something_else", headers=VIEWER_HEADERS)
    assert non_matching.json()["total_items"] == 0


def test_operations_endpoints_require_authentication(client):
    response = client.get("/api/v1/operations")
    assert response.status_code == 401
