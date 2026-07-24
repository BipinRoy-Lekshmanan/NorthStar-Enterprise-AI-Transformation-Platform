"""Tests for `ApprovalDecision` (`app.models.workflow`) and
`WorkflowEngine.approve()`'s handling of it -- decision validation,
reviewer/comments preservation, and rejecting an approval attempt on an
execution that isn't actually awaiting one. The pause/approve/reject/
request_changes/cancel *lifecycle* itself is covered end-to-end in
`tests/test_workflow_engine.py`; this file is about the decision record.
"""

import pytest
from pydantic import ValidationError

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
from app.workflows.engine import WorkflowEngine, WorkflowEngineError
from app.workflows.store import WorkflowStore


def test_valid_decision_values_are_accepted():
    for decision in ("approve", "reject", "request_changes", "cancel"):
        approval = ApprovalDecision(decision=decision)
        assert approval.decision == decision


def test_invalid_decision_value_is_rejected():
    with pytest.raises(ValidationError, match="decision"):
        ApprovalDecision(decision="maybe")


def test_decided_at_defaults_to_now_if_not_supplied():
    approval = ApprovalDecision(decision="approve")
    assert approval.decided_at is not None


def test_reviewer_and_comments_are_optional():
    approval = ApprovalDecision(decision="approve")
    assert approval.reviewer is None
    assert approval.comments is None


def _rag_settings(**overrides):
    defaults = dict(
        llm_provider="fake", llm_model="fake-echo-v1", llm_api_key=None,
        llm_temperature=0.0, llm_max_output_tokens=1024, llm_timeout_seconds=30.0,
        context_max_characters=6000, context_max_chunks=6, context_min_score=0.0,
        max_question_length=2000, insufficient_context_min_results=1, insufficient_context_min_score=0.0,
    )
    defaults.update(overrides)
    return RagSettings(**defaults)


def _build_engine(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "14_Testing_Strategy.md").write_text(
        "---\ndocument_id: NLC-ENG-005\ntitle: Testing Strategy\n---\n\n# Testing Strategy\n\nContent. " * 10,
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
    service = RagService(retriever, context_builder, FakeModelProvider(), _rag_settings(), default_top_k=10)
    store = WorkflowStore(tmp_path / "workflow_store")
    return WorkflowEngine(service, store, _rag_settings())


def test_approve_on_a_non_awaiting_execution_is_rejected(tmp_path):
    engine = _build_engine(tmp_path)
    execution = engine.run("production_readiness_review", {
        "release_name": "r", "services_affected": ["s"], "business_impact": "b",
        "deployment_strategy": "canary", "test_evidence": "e", "security_evidence": "e",
        "performance_evidence": "e", "rollback_plan": "e", "monitoring_plan": "e", "support_readiness": "e",
    })
    # No blocking evidence gap -> completes without ever pausing.
    assert execution.status == "completed"

    with pytest.raises(WorkflowEngineError, match="not awaiting approval"):
        engine.approve(execution.execution_id, ApprovalDecision(decision="approve"))


def test_approval_reviewer_and_comments_survive_a_store_round_trip(tmp_path):
    engine = _build_engine(tmp_path)
    execution = engine.run("production_readiness_review", {
        "release_name": "r", "services_affected": ["s"], "business_impact": "b",
        "deployment_strategy": "canary",
    })
    assert execution.status == "awaiting_approval"

    engine.approve(
        execution.execution_id,
        ApprovalDecision(decision="approve", reviewer="bipin", comments="proceed with conditions"),
    )

    reloaded = engine.store.load(execution.execution_id)
    approval_stage = next(r for r in reloaded.stage_results if r.structured_output.get("approval"))
    assert approval_stage.structured_output["approval"]["reviewer"] == "bipin"
    assert approval_stage.structured_output["approval"]["comments"] == "proceed with conditions"
