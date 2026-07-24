"""Tests for evaluation endpoints (Milestone 7): triggering a run (RBAC,
category dispatch, persistence), listing/getting run history. Both
evaluators' `DEFAULT_DATASET_PATH` module attribute is monkeypatched to
a tiny tmp_path dataset -- same technique as
`tests/test_evaluate_cli.py` -- so this never depends on the real
(large) knowledge base or the real seed evaluation datasets.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.services import (
    get_evaluation_run_store,
    get_rag_service,
    get_workflow_engine,
)
from app.api.main import create_app
from app.config.settings import IngestionSettings, RagSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.evaluation.run_store import EvaluationRunStore
from app.ingestion.pipeline import IngestionPipeline
from app.rag.context_builder import ContextBuilder
from app.rag.pipeline import RagService
from app.rag.retriever import Retriever
from app.services.llm_service import FakeModelProvider
from app.workflows.engine import WorkflowEngine
from app.workflows.store import WorkflowStore


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
    (kb_dir / "14_Testing_Strategy.md").write_text(
        "---\ndocument_id: NLC-ENG-005\ntitle: Testing Strategy\n---\n\n"
        "# Testing Strategy\n\n## Coverage\n\n" + ("Unit and integration test coverage is required. " * 15),
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


@pytest.fixture(autouse=True)
def _tiny_eval_datasets(tmp_path, monkeypatch):
    """A one-case dataset per category so a run never touches the real
    (large) knowledge base or the real seed datasets."""
    rag_dataset = tmp_path / "rag_dataset.json"
    rag_dataset.write_text(json.dumps([]), encoding="utf-8")
    monkeypatch.setattr("app.evaluation.rag_evaluator.DEFAULT_DATASET_PATH", rag_dataset)

    input_file = tmp_path / "input.json"
    input_file.write_text(
        json.dumps({
            "release_name": "r", "services_affected": ["s"], "business_impact": "b",
            "deployment_strategy": "canary", "rollback_plan": "yes",
        }),
        encoding="utf-8",
    )
    workflow_dataset = tmp_path / "workflow_dataset.json"
    workflow_dataset.write_text(
        json.dumps([{
            "id": "t1", "workflow_id": "production_readiness_review", "input_file": str(input_file),
        }]),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.evaluation.workflow_evaluator.DEFAULT_DATASET_PATH", workflow_dataset)


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
def client(users_file, tmp_path):
    service, workflow_engine = _build_service_and_engine(tmp_path)
    run_store = EvaluationRunStore(tmp_path / "evaluation_runs")

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_workflow_engine] = lambda: workflow_engine
    app.dependency_overrides[get_evaluation_run_store] = lambda: run_store

    with TestClient(app) as test_client:
        yield test_client


VIEWER_HEADERS = {"X-API-Key": "viewer-key"}
ENGINEER_HEADERS = {"X-API-Key": "engineer-key"}


def test_viewer_cannot_trigger_a_run(client):
    response = client.post("/api/v1/evaluation/runs", json={"category": "rag"}, headers=VIEWER_HEADERS)
    assert response.status_code == 403


def test_engineer_can_trigger_a_rag_run(client):
    response = client.post("/api/v1/evaluation/runs", json={"category": "rag"}, headers=ENGINEER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "rag"
    assert body["total_cases"] == 0
    assert body["status"] == "completed"


def test_engineer_can_trigger_a_workflow_run(client):
    response = client.post("/api/v1/evaluation/runs", json={"category": "workflows"}, headers=ENGINEER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "workflows"
    assert body["total_cases"] == 1
    assert "results" in body
    assert body["results"][0]["case_id"] == "t1"


def test_invalid_category_returns_422(client):
    response = client.post("/api/v1/evaluation/runs", json={"category": "bogus"}, headers=ENGINEER_HEADERS)
    assert response.status_code == 422


def test_a_run_is_persisted_and_listed(client):
    executed = client.post("/api/v1/evaluation/runs", json={"category": "workflows"}, headers=ENGINEER_HEADERS)
    run_id = executed.json()["run_id"]

    listed = client.get("/api/v1/evaluation/runs", headers=VIEWER_HEADERS)
    assert listed.status_code == 200
    body = listed.json()
    assert body["total_items"] == 1
    assert body["items"][0]["run_id"] == run_id


def test_list_runs_filters_by_category(client):
    client.post("/api/v1/evaluation/runs", json={"category": "rag"}, headers=ENGINEER_HEADERS)
    client.post("/api/v1/evaluation/runs", json={"category": "workflows"}, headers=ENGINEER_HEADERS)

    response = client.get("/api/v1/evaluation/runs?category=workflows", headers=VIEWER_HEADERS)
    body = response.json()
    assert body["total_items"] == 1
    assert body["items"][0]["category"] == "workflows"


def test_get_run_detail_includes_summary(client):
    executed = client.post("/api/v1/evaluation/runs", json={"category": "workflows"}, headers=ENGINEER_HEADERS)
    run_id = executed.json()["run_id"]

    response = client.get(f"/api/v1/evaluation/runs/{run_id}", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert "summary" in body
    assert "completed" in body["summary"]


def test_get_unknown_run_returns_404(client):
    response = client.get("/api/v1/evaluation/runs/does-not-exist", headers=VIEWER_HEADERS)
    assert response.status_code == 404


def test_evaluation_endpoints_require_authentication(client):
    response = client.get("/api/v1/evaluation/runs")
    assert response.status_code == 401
