"""Tests for `GET /health/ready` and `GET /platform/info` (Milestone 8).

Same tmp_path fixture KB + `FakeModelProvider` convention as
`tests/test_api_platform.py` -- never the real (large) knowledge base.
Uses a freshly-constructed app via `create_app()` inside a real `with
TestClient(...)` block (unlike `tests/test_api_foundation.py`'s
module-level `TestClient(app)`, which never runs the lifespan and so
never populates `app.state`).
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.services import get_rag_service
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
    (kb_dir / "doc.md").write_text(
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
        json.dumps([{"api_key": "viewer-key", "username": "v", "role": "viewer"}]), encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_USERS_FILE", str(path))
    return path


@pytest.fixture
def client(users_file, tmp_path):
    service = _build_service(tmp_path)
    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service

    with TestClient(app) as test_client:
        yield test_client


VIEWER_HEADERS = {"X-API-Key": "viewer-key"}


def test_readiness_is_unauthenticated(client):
    response = client.get("/api/v1/health/ready")
    assert response.status_code != 401


def test_readiness_returns_200_and_ready_true_when_healthy(client):
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["checks"]["retrieval_pipeline"] == "ok"
    assert body["checks"]["database"] == "ok"


def test_readiness_returns_503_when_a_dependency_check_fails(client, monkeypatch):
    def _broken_retrieve(*args, **kwargs):
        raise RuntimeError("simulated retrieval outage")

    service = client.app.dependency_overrides[get_rag_service]()
    monkeypatch.setattr(service.retriever, "retrieve", _broken_retrieve)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert "simulated retrieval outage" in body["checks"]["retrieval_pipeline"]


def test_platform_info_requires_authentication(client):
    response = client.get("/api/v1/platform/info")
    assert response.status_code == 401


def test_platform_info_returns_version_environment_prompt_and_schema(client):
    response = client.get("/api/v1/platform/info", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["version"]
    assert body["environment"] in ("local", "development", "test", "staging", "production")
    assert body["prompt_version"]
    # schema_version may be None in an environment without Alembic files
    # reachable, but in this repo's real checkout it resolves to a real
    # revision id -- either way the key must always be present.
    assert "schema_version" in body
