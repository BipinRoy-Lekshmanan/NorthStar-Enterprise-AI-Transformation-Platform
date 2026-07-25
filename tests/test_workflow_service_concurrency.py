"""Tests for Milestone 8's execution-locking in `app.api.services.workflow_service`
and `app.api.services.approval_service` -- a second, concurrent mutation of
the *same* execution_id (resume/cancel/approve, in any combination) must be
rejected with 409 CONCURRENCY_CONFLICT rather than allowed to double-process
a stage. Uses the same synthetic-workflow harness as `tests/test_workflow_engine.py`
(a controlled `WorkflowDefinition` registered via `monkeypatch.setitem`) --
no network, no API key.

`lock_registry=None` (the default used by every pre-existing caller) must
remain completely unaffected -- verified by `tests/test_api_workflows.py`/
`tests/test_api_approvals.py` continuing to pass unmodified.
"""

import pytest

import app.workflows.registry as registry_module
from app.api.errors import ApiError
from app.api.services.approval_service import record_approval
from app.api.services.workflow_service import cancel_execution, execution_lock_name, resume_execution
from app.config.settings import IngestionSettings, RagSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.ingestion.pipeline import IngestionPipeline
from app.rag.context_builder import ContextBuilder
from app.rag.pipeline import RagService
from app.rag.retriever import Retriever
from app.resilience.concurrency import LockRegistry
from app.services.llm_service import FakeModelProvider
from app.workflows.definitions import WorkflowDefinition, WorkflowStageDefinition, validate_definition
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
        "# Testing Strategy\n\n## Coverage\n\n"
        + ("Unit and integration test coverage is required before release. " * 15),
        encoding="utf-8",
    )
    return kb_dir


def _build_engine(tmp_path):
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
    return WorkflowEngine(service, store, _rag_settings())


def _stage(stage_id, stage_type="validate_input", **kwargs):
    return WorkflowStageDefinition(stage_id=stage_id, name=stage_id, stage_type=stage_type, **kwargs)


def _register_with_approval(monkeypatch):
    stages = (
        _stage("validate"),
        _stage(
            "approval", stage_type="human_approval", required=False, depends_on=("validate",),
            human_approval_required=True, approval_condition="always",
        ),
        _stage("report", stage_type="final_report", depends_on=("approval",)),
    )
    defn = WorkflowDefinition(
        workflow_id="synthetic", name="Synthetic", version="1.0.0", description="d",
        input_schema={"topic": {"type": "string", "required": True}},
        stages=stages, output_template=("Executive Summary", "Sources"),
    )
    validated = validate_definition(defn)
    monkeypatch.setitem(registry_module.WORKFLOW_REGISTRY, "synthetic", validated)
    return validated


def test_cancel_rejects_a_concurrent_cancel_on_the_same_execution(tmp_path, monkeypatch):
    _register_with_approval(monkeypatch)
    engine = _build_engine(tmp_path)
    execution = engine.run("synthetic", {"topic": "release"})
    assert execution.status == "awaiting_approval"  # non-terminal, cancellable

    lock_registry = LockRegistry()
    with lock_registry.acquire(execution_lock_name(execution.execution_id)):
        with pytest.raises(ApiError) as exc_info:
            cancel_execution(engine, execution.execution_id, lock_registry=lock_registry)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code.value == "CONCURRENCY_CONFLICT"
    # The rejected call never reached the engine -- status is unchanged.
    assert engine.store.load(execution.execution_id).status == "awaiting_approval"


def test_cancel_without_a_lock_registry_is_unaffected(tmp_path, monkeypatch):
    _register_with_approval(monkeypatch)
    engine = _build_engine(tmp_path)
    execution = engine.run("synthetic", {"topic": "release"})

    result = cancel_execution(engine, execution.execution_id)  # lock_registry=None (default)

    assert result.status == "cancelled"


def test_record_approval_rejects_a_concurrent_decision_on_the_same_execution(tmp_path, monkeypatch):
    _register_with_approval(monkeypatch)
    engine = _build_engine(tmp_path)
    execution = engine.run("synthetic", {"topic": "release"})
    assert execution.status == "awaiting_approval"

    lock_registry = LockRegistry()
    with lock_registry.acquire(execution_lock_name(execution.execution_id)):
        with pytest.raises(ApiError) as exc_info:
            record_approval(
                engine, execution.execution_id, "approve", "reviewer", "go ahead", lock_registry=lock_registry,
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code.value == "CONCURRENCY_CONFLICT"
    assert engine.store.load(execution.execution_id).status == "awaiting_approval"


def test_record_approval_without_a_lock_registry_is_unaffected(tmp_path, monkeypatch):
    _register_with_approval(monkeypatch)
    engine = _build_engine(tmp_path)
    execution = engine.run("synthetic", {"topic": "release"})

    result = record_approval(engine, execution.execution_id, "approve", "reviewer", "go ahead")

    assert result.status == "completed"


def test_resume_rejects_a_concurrent_resume_on_the_same_execution(tmp_path, monkeypatch):
    """A `running`-status execution (e.g. left behind by a crashed
    process, since `WorkflowEngine.run` normally runs synchronously to
    completion or to `awaiting_approval`) is the one case
    `resume_execution` actually accepts -- built directly via the store,
    mirroring how a real crash-recovery execution would be found on
    disk."""
    _register_with_approval(monkeypatch)
    engine = _build_engine(tmp_path)
    execution = engine.run("synthetic", {"topic": "release"})
    stalled = execution.model_copy(update={"status": "running", "current_stage": "report"})
    engine.store.save(stalled)

    lock_registry = LockRegistry()
    with lock_registry.acquire(execution_lock_name(stalled.execution_id)):
        with pytest.raises(ApiError) as exc_info:
            resume_execution(engine, stalled.execution_id, lock_registry=lock_registry)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code.value == "CONCURRENCY_CONFLICT"


def test_execution_lock_name_is_shared_across_resume_cancel_and_approve():
    """The whole point of one shared naming convention: a resume, a
    cancel, and an approve racing on the *same* execution_id must all
    contend for the *same* lock, not three independent ones."""
    assert execution_lock_name("exec-1") == execution_lock_name("exec-1")
    assert execution_lock_name("exec-1") != execution_lock_name("exec-2")
