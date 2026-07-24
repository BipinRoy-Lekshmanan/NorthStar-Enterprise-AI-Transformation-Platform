"""Tests for `app.evaluation.workflow_evaluator` -- eval case loading,
per-case checks, and aggregate metric computation. Real `WorkflowEngine`
+ `FakeModelProvider` + a small fixture KB -- no network, no API key.
"""

import json

from app.config.settings import PROJECT_ROOT, IngestionSettings, RagSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.evaluation.workflow_evaluator import (
    DEFAULT_DATASET_PATH,
    WorkflowEvalCase,
    _rate,
    evaluate_case,
    load_eval_cases,
    run_evaluation,
)
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


def _build_engine(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "15_Release_Management.md").write_text(
        "---\ndocument_id: NLC-ENG-006\ntitle: Release Management\n---\n\n# Release Management\n\nContent. " * 15,
        encoding="utf-8",
    )
    (kb_dir / "14_Testing_Strategy.md").write_text(
        "---\ndocument_id: NLC-ENG-005\ntitle: Testing Strategy\n---\n\n# Testing Strategy\n\nContent. " * 15,
        encoding="utf-8",
    )
    (kb_dir / "13_DevSecOps_Standards.md").write_text(
        "---\ndocument_id: NLC-ENG-004\ntitle: DevSecOps Standards\n---\n\n# DevSecOps Standards\n\nContent. " * 15,
        encoding="utf-8",
    )
    (kb_dir / "17_Platform_Engineering.md").write_text(
        "---\ndocument_id: NLC-ENG-008\ntitle: Platform Engineering\n---\n\n# Platform Engineering\n\nContent. " * 15,
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


def test_real_dataset_loads_and_has_at_least_ten_cases():
    assert DEFAULT_DATASET_PATH.exists()
    cases = load_eval_cases()
    assert len(cases) >= 10
    assert all(isinstance(case, WorkflowEvalCase) for case in cases)
    assert {case.workflow_id for case in cases} == {
        "architecture_review", "ai_solution_review", "production_readiness_review",
        "incident_review", "executive_ai_transformation_assessment",
    }


def test_evaluate_case_passes_when_expectations_match(tmp_path):
    engine = _build_engine(tmp_path)
    input_file = tmp_path / "input.json"
    input_file.write_text(
        json.dumps({
            "release_name": "r", "services_affected": ["s"], "business_impact": "b", "deployment_strategy": "canary",
        }),
        encoding="utf-8",
    )
    # `_load_input` resolves `input_file` relative to PROJECT_ROOT; an absolute
    # path (as tmp_path fixtures are) still works since PROJECT_ROOT / <absolute>
    # collapses to the absolute path itself under pathlib's `/` operator.
    case = WorkflowEvalCase(
        id="t1", workflow_id="production_readiness_review", input_file=str(input_file),
        expected_findings=["rollback"], expected_final_recommendation="INSUFFICIENT_EVIDENCE",
        requires_citations=True, requires_human_approval=True,
    )

    result = evaluate_case(engine, case)

    assert result.passed is True
    assert result.checks["completed"] is True
    assert result.checks["final_recommendation_matches"] is True


def test_evaluate_case_fails_when_expected_recommendation_does_not_match(tmp_path):
    engine = _build_engine(tmp_path)
    input_file = tmp_path / "input.json"
    input_file.write_text(
        json.dumps({
            "release_name": "r", "services_affected": ["s"], "business_impact": "b", "deployment_strategy": "canary",
            "rollback_plan": "yes",
        }),
        encoding="utf-8",
    )
    case = WorkflowEvalCase(
        id="t2", workflow_id="production_readiness_review", input_file=str(input_file),
        expected_final_recommendation="NO_GO",  # actual will be GO since only rollback_plan is provided as evidence
    )

    result = evaluate_case(engine, case)

    assert result.passed is False
    assert result.checks["final_recommendation_matches"] is False
    assert any("NO_GO" in note for note in result.notes)


def test_evaluate_case_fails_when_expected_stage_did_not_run(tmp_path):
    engine = _build_engine(tmp_path)
    input_file = tmp_path / "input.json"
    input_file.write_text(
        json.dumps({
            "incident_title": "t", "severity": "Sev-2", "start_time": "2026-01-01T00:00:00Z",
            "customer_impact": "c", "systems_affected": ["s"], "security_related": "no",
        }),
        encoding="utf-8",
    )
    # Note: a *skipped* stage (e.g. security_review when security_related=no) still
    # appears in stage_results, so expected_stages_executed would still pass for it --
    # use a stage id that genuinely never runs to exercise the failure path.
    case = WorkflowEvalCase(
        id="t3", workflow_id="incident_review", input_file=str(input_file),
        expected_stages=["stage_that_does_not_exist"], approval_decision="approve",
    )

    result = evaluate_case(engine, case)

    assert result.checks["expected_stages_executed"] is False
    assert any("stage_that_does_not_exist" in note for note in result.notes)


def test_run_evaluation_returns_one_result_per_case(tmp_path):
    engine = _build_engine(tmp_path)
    input_file = tmp_path / "input.json"
    input_file.write_text(
        json.dumps({
            "release_name": "r", "services_affected": ["s"], "business_impact": "b", "deployment_strategy": "canary",
            "rollback_plan": "yes",
        }),
        encoding="utf-8",
    )
    cases = [
        WorkflowEvalCase(id="a", workflow_id="production_readiness_review", input_file=str(input_file)),
        WorkflowEvalCase(id="b", workflow_id="production_readiness_review", input_file=str(input_file)),
    ]
    results = run_evaluation(engine, cases)
    assert [r.case_id for r in results] == ["a", "b"]


def test_rate_helper_computes_fraction_of_passing_checks(tmp_path):
    engine = _build_engine(tmp_path)
    input_file = tmp_path / "input.json"
    input_file.write_text(
        json.dumps({
            "release_name": "r", "services_affected": ["s"], "business_impact": "b", "deployment_strategy": "canary",
            "rollback_plan": "yes",
        }),
        encoding="utf-8",
    )
    passing_case = WorkflowEvalCase(id="pass", workflow_id="production_readiness_review", input_file=str(input_file))
    failing_case = WorkflowEvalCase(
        id="fail", workflow_id="production_readiness_review", input_file=str(input_file),
        expected_final_recommendation="NO_GO",
    )
    results = run_evaluation(engine, [passing_case, failing_case])

    assert _rate(results, "completed") == 1.0
    assert _rate(results, "final_recommendation_matches") == 0.5
