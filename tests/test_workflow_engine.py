"""Tests for `app.workflows.engine.WorkflowEngine` -- deterministic stage
execution, dependency enforcement, required/optional failure handling,
stage skipping, and the pause/approve/resume/cancel lifecycle.

Uses a synthetic `WorkflowDefinition` (isolating engine mechanics from
specific advisor content, same reasoning `tests/test_router.py` uses
synthetic advisors) registered into the real registry via
`monkeypatch.setitem` -- `WorkflowEngine` always calls the real
`app.workflows.registry.get_workflow`, so this is the lightest way to
inject a controlled definition without changing production code. Real
`RagService` (Milestone 1-3 infrastructure, untouched) + `FakeModelProvider`
+ a small fixture KB -- no network, no API key. The 5 real catalog
workflows get their own end-to-end coverage in `tests/test_workflow_e2e.py`.
"""

import app.workflows.registry as registry_module
import pytest

from app.config.settings import IngestionSettings, RagSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.ingestion.pipeline import IngestionPipeline
from app.models.workflow import ApprovalDecision
from app.rag.context_builder import ContextBuilder
from app.rag.pipeline import RagService
from app.rag.retriever import Retriever
from app.services.llm_service import FakeModelProvider, ModelUnavailableError
from app.workflows.definitions import WorkflowDefinition, WorkflowStageDefinition, validate_definition
from app.workflows.engine import WorkflowEngine, WorkflowEngineError
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
        "# Testing Strategy\n\n## Coverage\n\n"
        + ("Unit and integration test coverage is required before release. " * 15),
        encoding="utf-8",
    )
    return kb_dir


def _build_engine(tmp_path, llm=None):
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
    service = RagService(retriever, context_builder, llm or FakeModelProvider(), _rag_settings(), default_top_k=10)
    store = WorkflowStore(tmp_path / "workflow_store")
    return WorkflowEngine(service, store, _rag_settings())


def _stage(stage_id, stage_type="validate_input", **kwargs):
    return WorkflowStageDefinition(stage_id=stage_id, name=stage_id, stage_type=stage_type, **kwargs)


def _register(monkeypatch, stages, **kwargs):
    defn = WorkflowDefinition(
        workflow_id="synthetic", name="Synthetic", version="1.0.0", description="d",
        input_schema={"topic": {"type": "string", "required": True}},
        stages=tuple(stages), output_template=("Executive Summary", "Sources"), **kwargs,
    )
    validated = validate_definition(defn)
    monkeypatch.setitem(registry_module.WORKFLOW_REGISTRY, "synthetic", validated)
    return validated


_QUESTION = "What testing requirements apply to {topic}?"


class _FailingProvider:
    def generate(self, **kwargs):
        raise ModelUnavailableError("simulated provider outage")


def test_stages_execute_in_deterministic_order(tmp_path, monkeypatch):
    stages = (
        _stage("validate"),
        _stage("review_a", stage_type="advisor_review", advisor_name="testing", depends_on=("validate",), question_template=_QUESTION),
        _stage("conflict", stage_type="conflict_review", depends_on=("review_a",)),
        _stage("report", stage_type="final_report", depends_on=("conflict",)),
    )
    _register(monkeypatch, stages)
    engine = _build_engine(tmp_path)

    execution = engine.run("synthetic", {"topic": "release"})

    assert [r.stage_id for r in execution.stage_results] == ["validate", "review_a", "conflict", "report"]
    assert execution.status == "completed"


def test_required_stage_failure_halts_the_workflow(tmp_path, monkeypatch):
    stages = (
        _stage("validate"),
        _stage("review", stage_type="advisor_review", advisor_name="testing", depends_on=("validate",), question_template=_QUESTION),
    )
    _register(monkeypatch, stages)
    engine = _build_engine(tmp_path)

    # Missing the required "topic" field -> validate_input fails -> halts before review ever runs.
    execution = engine.run("synthetic", {})

    assert execution.status == "failed"
    assert [r.stage_id for r in execution.stage_results] == ["validate"]
    assert execution.stage_results[0].status == "failed"


def test_optional_stage_failure_does_not_halt_the_workflow(tmp_path, monkeypatch):
    stages = (
        _stage("validate"),
        _stage(
            "synthesis", stage_type="executive_synthesis", required=False,
            depends_on=("validate",), question_template=_QUESTION,
        ),
        _stage("report", stage_type="final_report", depends_on=("synthesis",)),
    )
    _register(monkeypatch, stages)
    engine = _build_engine(tmp_path, llm=_FailingProvider())

    execution = engine.run("synthetic", {"topic": "release"})

    assert execution.status == "completed"
    synthesis_result = next(r for r in execution.stage_results if r.stage_id == "synthesis")
    assert synthesis_result.status == "failed"
    assert execution.errors  # the failure is visible, not silently swallowed
    assert any(r.stage_id == "report" for r in execution.stage_results)


def test_human_approval_stage_is_skipped_when_condition_not_met(tmp_path, monkeypatch):
    stages = (
        _stage("validate"),
        _stage(
            "approval", stage_type="human_approval", required=False, depends_on=("validate",),
            human_approval_required=True, approval_condition="on_blocking_finding",
        ),
        _stage("report", stage_type="final_report", depends_on=("approval",)),
    )
    _register(monkeypatch, stages)
    engine = _build_engine(tmp_path)

    execution = engine.run("synthetic", {"topic": "release"})

    assert execution.status == "completed"
    approval_result = next(r for r in execution.stage_results if r.stage_id == "approval")
    assert approval_result.status == "skipped"


def test_advisor_review_stage_is_skipped_when_skip_condition_not_truthy(tmp_path, monkeypatch):
    stages = (
        _stage("validate"),
        _stage(
            "review", stage_type="advisor_review", advisor_name="testing", depends_on=("validate",),
            question_template=_QUESTION, skip_unless_input_truthy="run_review",
        ),
        _stage("report", stage_type="final_report", depends_on=("review",)),
    )
    _register(monkeypatch, stages)
    engine = _build_engine(tmp_path)

    execution = engine.run("synthetic", {"topic": "release", "run_review": "no"})

    review_result = next(r for r in execution.stage_results if r.stage_id == "review")
    assert review_result.status == "skipped"
    assert execution.status == "completed"


def test_unconditional_human_approval_pauses_execution(tmp_path, monkeypatch):
    stages = (
        _stage("validate"),
        _stage(
            "approval", stage_type="human_approval", required=False, depends_on=("validate",),
            human_approval_required=True, approval_condition="always",
        ),
        _stage("report", stage_type="final_report", depends_on=("approval",)),
    )
    _register(monkeypatch, stages)
    engine = _build_engine(tmp_path)

    execution = engine.run("synthetic", {"topic": "release"})

    assert execution.status == "awaiting_approval"
    assert execution.current_stage == "approval"
    assert not any(r.stage_id == "report" for r in execution.stage_results)


def test_approve_resumes_and_completes_the_workflow(tmp_path, monkeypatch):
    stages = (
        _stage("validate"),
        _stage(
            "approval", stage_type="human_approval", required=False, depends_on=("validate",),
            human_approval_required=True, approval_condition="always",
        ),
        _stage("report", stage_type="final_report", depends_on=("approval",)),
    )
    _register(monkeypatch, stages)
    engine = _build_engine(tmp_path)

    execution = engine.run("synthetic", {"topic": "release"})
    resumed = engine.approve(
        execution.execution_id, ApprovalDecision(decision="approve", reviewer="bipin", comments="go ahead")
    )

    assert resumed.status == "completed"
    stage_ids = [r.stage_id for r in resumed.stage_results]
    assert stage_ids == ["validate", "approval", "report"]
    assert len(stage_ids) == len(set(stage_ids))  # no duplicate stage execution

    approval_result = next(r for r in resumed.stage_results if r.stage_id == "approval")
    assert approval_result.structured_output["approval"]["comments"] == "go ahead"


def test_reject_decision_is_terminal(tmp_path, monkeypatch):
    stages = (
        _stage("validate"),
        _stage(
            "approval", stage_type="human_approval", required=False, depends_on=("validate",),
            human_approval_required=True, approval_condition="always",
        ),
        _stage("report", stage_type="final_report", depends_on=("approval",)),
    )
    _register(monkeypatch, stages)
    engine = _build_engine(tmp_path)

    execution = engine.run("synthetic", {"topic": "release"})
    rejected = engine.approve(execution.execution_id, ApprovalDecision(decision="reject"))

    assert rejected.status == "cancelled"
    with pytest.raises(WorkflowEngineError, match="terminal status"):
        engine.resume(rejected.execution_id)


def test_request_changes_decision_sets_changes_requested_status(tmp_path, monkeypatch):
    stages = (
        _stage("validate"),
        _stage(
            "approval", stage_type="human_approval", required=False, depends_on=("validate",),
            human_approval_required=True, approval_condition="always",
        ),
        _stage("report", stage_type="final_report", depends_on=("approval",)),
    )
    _register(monkeypatch, stages)
    engine = _build_engine(tmp_path)

    execution = engine.run("synthetic", {"topic": "release"})
    result = engine.approve(execution.execution_id, ApprovalDecision(decision="request_changes", comments="fix x"))

    assert result.status == "changes_requested"


def test_cancel_marks_execution_terminal_and_blocks_resume(tmp_path, monkeypatch):
    stages = (
        _stage("validate"),
        _stage(
            "approval", stage_type="human_approval", required=False, depends_on=("validate",),
            human_approval_required=True, approval_condition="always",
        ),
        _stage("report", stage_type="final_report", depends_on=("approval",)),
    )
    _register(monkeypatch, stages)
    engine = _build_engine(tmp_path)

    execution = engine.run("synthetic", {"topic": "release"})
    cancelled = engine.cancel(execution.execution_id)

    assert cancelled.status == "cancelled"
    with pytest.raises(WorkflowEngineError, match="terminal status"):
        engine.resume(cancelled.execution_id)


def test_completed_execution_cannot_be_resumed(tmp_path, monkeypatch):
    stages = (_stage("validate"), _stage("report", stage_type="final_report", depends_on=("validate",)))
    _register(monkeypatch, stages)
    engine = _build_engine(tmp_path)

    execution = engine.run("synthetic", {"topic": "release"})
    assert execution.status == "completed"

    with pytest.raises(WorkflowEngineError, match="terminal status"):
        engine.resume(execution.execution_id)


def test_awaiting_approval_execution_cannot_be_resumed_directly(tmp_path, monkeypatch):
    stages = (
        _stage("validate"),
        _stage(
            "approval", stage_type="human_approval", required=False, depends_on=("validate",),
            human_approval_required=True, approval_condition="always",
        ),
    )
    _register(monkeypatch, stages)
    engine = _build_engine(tmp_path)

    execution = engine.run("synthetic", {"topic": "release"})
    with pytest.raises(WorkflowEngineError, match="call approve"):
        engine.resume(execution.execution_id)


def test_disabled_workflow_cannot_be_run(tmp_path, monkeypatch):
    stages = (_stage("validate"),)
    _register(monkeypatch, stages, enabled=False)
    engine = _build_engine(tmp_path)

    with pytest.raises(WorkflowEngineError, match="disabled"):
        engine.run("synthetic", {"topic": "release"})


def test_execution_persists_across_a_fresh_engine_instance(tmp_path, monkeypatch):
    stages = (
        _stage("validate"),
        _stage(
            "approval", stage_type="human_approval", required=False, depends_on=("validate",),
            human_approval_required=True, approval_condition="always",
        ),
    )
    _register(monkeypatch, stages)
    engine = _build_engine(tmp_path)
    execution = engine.run("synthetic", {"topic": "release"})

    # Simulate a fresh process: a brand-new engine pointed at the same store dir.
    kb_dir = tmp_path / "kb"
    provider = LocalHashingEmbeddingProvider(dimensions=128)
    vector_store = LocalVectorStore(tmp_path / "vstore")
    retriever = Retriever(provider, vector_store)
    context_builder = ContextBuilder(
        max_characters=6000, max_chunks=6, min_score=0.0, insufficient_min_results=1, insufficient_min_score=0.0,
    )
    service = RagService(retriever, context_builder, FakeModelProvider(), _rag_settings(), default_top_k=10)
    fresh_engine = WorkflowEngine(service, WorkflowStore(tmp_path / "workflow_store"), _rag_settings())

    reloaded = fresh_engine.store.load(execution.execution_id)
    assert reloaded.status == "awaiting_approval"
    assert reloaded.execution_id == execution.execution_id
