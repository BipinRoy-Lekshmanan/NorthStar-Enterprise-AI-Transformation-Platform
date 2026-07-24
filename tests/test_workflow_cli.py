"""Tests for `app.workflows.cli` -- pure formatting helpers directly, plus
a handful of full `main()` invocations (monkeypatched `sys.argv` and a
monkeypatched `build_default_workflow_engine`) exercising `list`,
`describe`, `run`, and `approve`.
"""

import json
from datetime import datetime, timezone

import pytest

import app.workflows.cli as cli
from app.config.settings import IngestionSettings, RagSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.ingestion.pipeline import IngestionPipeline
from app.models.workflow import WorkflowExecution, WorkflowStageResult
from app.rag.context_builder import ContextBuilder
from app.rag.pipeline import RagService
from app.rag.retriever import Retriever
from app.services.llm_service import FakeModelProvider
from app.workflows.engine import WorkflowEngine
from app.workflows.store import WorkflowStore

_NOW = datetime.now(timezone.utc)


def _execution(**overrides):
    defaults = dict(execution_id="e1", workflow_id="w1", workflow_version="1.0.0", status="completed")
    defaults.update(overrides)
    return WorkflowExecution(**defaults)


# -- formatting helpers -----------------------------------------------------------------------


def test_format_execution_summary_includes_key_fields():
    execution = _execution(status="awaiting_approval", current_stage="approval")
    text = cli._format_execution_summary(execution)
    assert "e1" in text
    assert "awaiting_approval" in text
    assert "approve e1" in text  # points the reader at the next command


def test_format_execution_summary_shows_warnings_and_errors():
    execution = _execution(warnings=["w1"], errors=["e1-error"])
    text = cli._format_execution_summary(execution)
    assert "w1" in text
    assert "e1-error" in text


def test_format_stages_lists_every_stage_result():
    execution = _execution(stage_results=[
        WorkflowStageResult(stage_id="validate", stage_name="Validate", status="completed", started_at=_NOW),
        WorkflowStageResult(
            stage_id="review", stage_name="Review", status="completed", started_at=_NOW, advisor_name="testing"
        ),
    ])
    text = cli._format_stages(execution)
    assert "validate" in text
    assert "advisor=testing" in text


def test_format_findings_shows_none_when_empty():
    assert "(none)" in cli._format_findings(_execution())


def test_format_findings_shows_blocking_tag():
    execution = _execution(stage_results=[
        WorkflowStageResult(
            stage_id="validate", stage_name="Validate", status="completed", started_at=_NOW,
            structured_output={
                "evidence_gaps": [
                    {"field": "rollback_plan", "description": "missing", "severity": "critical", "blocking": True}
                ]
            },
        ),
    ])
    text = cli._format_findings(execution)
    assert "[BLOCKING]" in text
    assert "rollback_plan" in text


def test_render_output_json_format_is_valid_json():
    class _Args:
        output_format = "json"

    parsed = json.loads(cli._render_output(_execution(), _Args()))
    assert parsed["execution_id"] == "e1"


def test_format_report_extracts_the_final_report_stage():
    execution = _execution(stage_results=[
        WorkflowStageResult(
            stage_id="report", stage_name="Report", status="completed", started_at=_NOW,
            structured_output={"report_sections": {"Executive Summary": "All good."}},
        ),
    ])
    text = cli._format_report(execution)
    assert "Executive Summary" in text
    assert "All good." in text


# -- end-to-end main() invocations -----------------------------------------------------------------


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


def test_main_list_command_prints_all_workflows(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["app.workflows", "list"])
    cli.main()
    output = capsys.readouterr().out
    assert "production_readiness_review" in output
    assert "architecture_review" in output


def test_main_describe_command_prints_stages(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["app.workflows", "describe", "production_readiness_review"])
    cli.main()
    assert "validate_release_input" in capsys.readouterr().out


def test_main_describe_unknown_workflow_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["app.workflows", "describe", "does-not-exist"])
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 1
    assert "Invalid workflow" in capsys.readouterr().out


def test_main_run_command_executes_and_prints_summary(monkeypatch, capsys, tmp_path):
    engine = _build_engine(tmp_path)
    monkeypatch.setattr(cli, "build_default_workflow_engine", lambda: engine)

    input_file = tmp_path / "input.json"
    input_file.write_text(
        json.dumps({
            "release_name": "r", "services_affected": ["s"], "business_impact": "b", "deployment_strategy": "canary",
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        ["app.workflows", "run", "production_readiness_review", "--input", str(input_file), "--show-findings"],
    )
    cli.main()
    output = capsys.readouterr().out
    assert "Execution:" in output
    assert "awaiting_approval" in output  # rollback_plan missing -> blocking gap -> pauses


def test_main_run_command_missing_input_file_exits_nonzero(monkeypatch, capsys, tmp_path):
    engine = _build_engine(tmp_path)
    monkeypatch.setattr(cli, "build_default_workflow_engine", lambda: engine)
    monkeypatch.setattr(
        "sys.argv",
        ["app.workflows", "run", "production_readiness_review", "--input", str(tmp_path / "missing.json")],
    )

    with pytest.raises(SystemExit):
        cli.main()
    assert "not found" in capsys.readouterr().out


def test_main_approve_then_status_round_trip(monkeypatch, capsys, tmp_path):
    engine = _build_engine(tmp_path)
    monkeypatch.setattr(cli, "build_default_workflow_engine", lambda: engine)

    input_file = tmp_path / "input.json"
    input_file.write_text(
        json.dumps({
            "release_name": "r", "services_affected": ["s"], "business_impact": "b", "deployment_strategy": "canary",
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["app.workflows", "run", "production_readiness_review", "--input", str(input_file)])
    cli.main()
    capsys.readouterr()
    execution_id = engine.store.list_execution_ids()[0]

    monkeypatch.setattr(
        "sys.argv", ["app.workflows", "approve", execution_id, "--decision", "approve", "--comments", "go"]
    )
    cli.main()
    assert "completed" in capsys.readouterr().out
