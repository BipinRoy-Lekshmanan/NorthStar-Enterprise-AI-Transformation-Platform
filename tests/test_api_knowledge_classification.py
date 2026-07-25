"""API-level tests for the data-classification guardrail (Milestone 8):
a Restricted document must be invisible to any role below
ADMINISTRATOR across listing, detail, and search -- a small dedicated
tmp_path fixture KB (one Internal doc, one Restricted doc), separate
from `tests/test_api_knowledge.py`'s fixture so its existing
`total_items == 2` assertions don't need to account for a 3rd document.
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
    (kb_dir / "public_doc.md").write_text(
        "---\ndocument_id: PUBLIC-DOC\ntitle: Public Doc\nclassification: Internal\n---\n\n"
        "# Public Doc\n\n## Section\n\n" + ("Ordinary internal content about testing strategy. " * 15),
        encoding="utf-8",
    )
    (kb_dir / "restricted_doc.md").write_text(
        "---\ndocument_id: RESTRICTED-DOC\ntitle: Restricted Doc\nclassification: Restricted\n---\n\n"
        "# Restricted Doc\n\n## Section\n\n" + ("Highly sensitive restricted content. " * 15),
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


def _build_indexed_service(kb_dir, ingestion_settings, retrieval_settings):
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
    kb_dir = _seed_kb(tmp_path / "kb")
    ingestion_settings = _ingestion_settings(tmp_path, kb_dir)
    retrieval_settings = _retrieval_settings(tmp_path)
    service = _build_indexed_service(kb_dir, ingestion_settings, retrieval_settings)

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_rag_settings] = lambda: _rag_settings()
    app.dependency_overrides[get_router_settings] = lambda: _router_settings()
    app.dependency_overrides[get_ingestion_settings] = lambda: ingestion_settings
    app.dependency_overrides[get_retrieval_settings] = lambda: retrieval_settings

    with TestClient(app) as test_client:
        yield test_client


VIEWER_HEADERS = {"X-API-Key": "viewer-key"}
REVIEWER_HEADERS = {"X-API-Key": "reviewer-key"}
ADMIN_HEADERS = {"X-API-Key": "admin-key"}


def test_viewer_does_not_see_the_restricted_document_in_the_listing(client):
    response = client.get("/api/v1/knowledge/documents", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 1
    assert body["items"][0]["document_id"] == "PUBLIC-DOC"


def test_reviewer_does_not_see_the_restricted_document_either(client):
    """Restricted requires ADMINISTRATOR specifically -- reviewer (the
    next tier down) is still not privileged enough."""
    response = client.get("/api/v1/knowledge/documents", headers=REVIEWER_HEADERS)
    body = response.json()
    assert body["total_items"] == 1


def test_administrator_sees_both_documents_in_the_listing(client):
    response = client.get("/api/v1/knowledge/documents", headers=ADMIN_HEADERS)
    body = response.json()
    assert body["total_items"] == 2
    ids = {item["document_id"] for item in body["items"]}
    assert ids == {"PUBLIC-DOC", "RESTRICTED-DOC"}


def test_viewer_gets_404_for_the_restricted_document_detail(client):
    response = client.get("/api/v1/knowledge/documents/RESTRICTED-DOC", headers=VIEWER_HEADERS)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_administrator_can_get_the_restricted_document_detail(client):
    response = client.get("/api/v1/knowledge/documents/RESTRICTED-DOC", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    assert response.json()["title"] == "Restricted Doc"


def test_viewer_gets_the_public_document_detail_normally(client):
    response = client.get("/api/v1/knowledge/documents/PUBLIC-DOC", headers=VIEWER_HEADERS)
    assert response.status_code == 200


def test_viewer_search_never_returns_restricted_chunks(client):
    response = client.post(
        "/api/v1/knowledge/search", json={"question": "sensitive restricted content", "top_k": 10},
        headers=VIEWER_HEADERS,
    )
    assert response.status_code == 200
    document_ids = {r["document_id"] for r in response.json()["results"]}
    assert "RESTRICTED-DOC" not in document_ids


def test_administrator_search_can_return_restricted_chunks(client):
    response = client.post(
        "/api/v1/knowledge/search", json={"question": "sensitive restricted content", "top_k": 10},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    document_ids = {r["document_id"] for r in response.json()["results"]}
    assert "RESTRICTED-DOC" in document_ids


def test_viewer_query_citations_never_include_the_restricted_document(client):
    """FakeModelProvider cites whichever [S#] markers it finds in the
    rendered prompt -- the "security" advisor has no document_id filter
    of its own, so both seeded documents are eligible context and the
    Restricted one would normally be cited alongside the Public one."""
    response = client.post(
        "/api/v1/query",
        json={"question": "sensitive restricted content", "advisor": "security", "max_supporting_advisors": 0},
        headers=VIEWER_HEADERS,
    )
    assert response.status_code == 200
    for citation in response.json()["citations"]:
        assert citation["document_id"] != "RESTRICTED-DOC"


def test_administrator_query_citations_can_include_the_restricted_document(client):
    response = client.post(
        "/api/v1/query",
        json={"question": "sensitive restricted content", "advisor": "security", "max_supporting_advisors": 0},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    document_ids = {c["document_id"] for c in response.json()["citations"]}
    assert "RESTRICTED-DOC" in document_ids
