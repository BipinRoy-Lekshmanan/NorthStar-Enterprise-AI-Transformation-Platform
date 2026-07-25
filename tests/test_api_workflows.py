"""Tests for workflow endpoints (Milestone 7): list/describe/examples,
execute, list/get executions, resume/cancel preconditions, and the
final report. Uses the real `architecture_review` catalog workflow
(always pauses for human approval before synthesis) against a small
tmp_path fixture KB + `FakeModelProvider` -- never the real KB/vector
store/workflow store. Approval itself is out of scope here (a separate
`approvals` router owns it) -- tests advance a paused execution to
"completed" via a direct `engine.approve()` call, exactly like
`tests/test_workflow_e2e.py`'s `_approve_if_paused` helper, then assert
the API's read endpoints reflect that state.
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
from app.models.workflow import ApprovalDecision
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


def _build_service_and_engine(tmp_path) -> tuple[RagService, WorkflowEngine]:
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
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_USERS_FILE", str(path))
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit_log"))
    # Restricted-document filtering (Milestone 8) resolves IngestionSettings
    # via app.state -- without this override every request would silently
    # re-run ingestion against the real enterprise_knowledge_base/ instead
    # of this test's own tmp_path fixture KB.
    monkeypatch.setenv("KNOWLEDGE_BASE_DIRS", str(tmp_path / "kb"))
    return path


@pytest.fixture
def service_and_engine(tmp_path):
    return _build_service_and_engine(tmp_path)


@pytest.fixture
def engine(service_and_engine):
    return service_and_engine[1]


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


def test_list_workflows_returns_all_five(client):
    response = client.get("/api/v1/workflows", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    workflow_ids = {w["workflow_id"] for w in response.json()}
    assert workflow_ids == {
        "architecture_review", "ai_solution_review", "production_readiness_review",
        "incident_review", "executive_ai_transformation_assessment",
    }


def test_get_workflow_detail_includes_stages_and_input_schema(client):
    response = client.get("/api/v1/workflows/architecture_review", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["stages"]
    assert "solution_name" in body["input_schema"]


def test_get_unknown_workflow_returns_404(client):
    response = client.get("/api/v1/workflows/does_not_exist", headers=VIEWER_HEADERS)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_list_examples_returns_named_payloads(client):
    response = client.get("/api/v1/workflows/architecture_review/examples", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body
    assert body[0]["inputs"]["solution_name"]


def test_viewer_cannot_execute_workflow(client):
    response = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=VIEWER_HEADERS,
    )
    assert response.status_code == 403


def test_engineer_can_execute_workflow_and_it_pauses_for_approval(client):
    response = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=ENGINEER_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_approval"
    assert body["execution_id"]


def test_execute_with_the_same_idempotency_key_replays_the_first_execution(client):
    headers = {**ENGINEER_HEADERS, "Idempotency-Key": "retry-key-1"}

    first = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=headers,
    )
    second = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["execution_id"] == second.json()["execution_id"]
    # Confirms the second call never re-ran the engine -- only one execution exists.
    listing = client.get("/api/v1/workflows/executions", headers=VIEWER_HEADERS)
    assert listing.json()["total_items"] == 1


def test_execute_without_an_idempotency_key_creates_a_new_execution_each_time(client):
    first = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=ENGINEER_HEADERS,
    )
    second = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=ENGINEER_HEADERS,
    )

    assert first.json()["execution_id"] != second.json()["execution_id"]


def test_execute_with_a_reused_idempotency_key_but_a_different_body_is_rejected(client):
    headers = {**ENGINEER_HEADERS, "Idempotency-Key": "retry-key-2"}
    client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=headers,
    )

    different_inputs = {**_ARCHITECTURE_REVIEW_INPUTS, "solution_name": "A Different Solution"}
    response = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": different_inputs}, headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_list_executions_returns_the_new_execution(client):
    client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=ENGINEER_HEADERS,
    )
    response = client.get("/api/v1/workflows/executions", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 1
    assert body["items"][0]["workflow_id"] == "architecture_review"


def test_get_execution_returns_findings_and_evidence_gaps_fields(client):
    execute_response = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=ENGINEER_HEADERS,
    )
    execution_id = execute_response.json()["execution_id"]
    response = client.get(f"/api/v1/workflows/executions/{execution_id}", headers=VIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert "findings" in body
    assert "evidence_gaps" in body
    assert "conflicts" in body


def test_get_unknown_execution_returns_404(client):
    response = client.get("/api/v1/workflows/executions/does-not-exist", headers=VIEWER_HEADERS)
    assert response.status_code == 404


def test_resume_while_awaiting_approval_returns_409_with_specific_code(client):
    execute_response = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=ENGINEER_HEADERS,
    )
    execution_id = execute_response.json()["execution_id"]
    response = client.post(f"/api/v1/workflows/executions/{execution_id}/resume", headers=ENGINEER_HEADERS)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKFLOW_AWAITING_APPROVAL"


def test_report_not_available_before_completion(client):
    execute_response = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=ENGINEER_HEADERS,
    )
    execution_id = execute_response.json()["execution_id"]
    response = client.get(f"/api/v1/workflows/executions/{execution_id}/report", headers=VIEWER_HEADERS)
    assert response.status_code == 404


def test_completed_execution_exposes_report_and_blocks_cancel(client, engine):
    execute_response = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=ENGINEER_HEADERS,
    )
    execution_id = execute_response.json()["execution_id"]

    # Approval itself belongs to a separate router (Task #78) -- advance
    # the paused execution directly via the real engine, mirroring
    # `tests/test_workflow_e2e.py`'s `_approve_if_paused` helper.
    engine.approve(execution_id, ApprovalDecision(decision="approve", reviewer="test"))

    detail = client.get(f"/api/v1/workflows/executions/{execution_id}", headers=VIEWER_HEADERS)
    assert detail.json()["status"] == "completed"

    report = client.get(f"/api/v1/workflows/executions/{execution_id}/report", headers=VIEWER_HEADERS)
    assert report.status_code == 200
    assert report.json()["sections"]

    cancel = client.post(f"/api/v1/workflows/executions/{execution_id}/cancel", headers=ENGINEER_HEADERS)
    assert cancel.status_code == 409
    assert cancel.json()["error"]["code"] == "WORKFLOW_ALREADY_COMPLETED"

    markdown_report = client.get(
        f"/api/v1/workflows/executions/{execution_id}/report?format=markdown", headers=VIEWER_HEADERS,
    )
    assert markdown_report.status_code == 200
    assert markdown_report.headers["content-type"].startswith("text/markdown")
    assert "architecture_review" in markdown_report.text
    assert "Northstar Lending Corporation is a fictional company" in markdown_report.text


def test_cancel_a_running_execution(client, engine):
    execute_response = client.post(
        "/api/v1/workflows/architecture_review/execute", json={"inputs": _ARCHITECTURE_REVIEW_INPUTS},
        headers=ENGINEER_HEADERS,
    )
    execution_id = execute_response.json()["execution_id"]
    response = client.post(f"/api/v1/workflows/executions/{execution_id}/cancel", headers=ENGINEER_HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_workflow_endpoints_require_authentication(client):
    response = client.get("/api/v1/workflows")
    assert response.status_code == 401
