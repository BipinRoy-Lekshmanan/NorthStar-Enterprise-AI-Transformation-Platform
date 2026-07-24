"""Tests for `app.evaluation.rag_evaluator.main()`'s `--category` dispatch
-- `--category workflows` defers entirely to
`app.evaluation.workflow_evaluator`; the default (`rag`, or omitted)
keeps running the Milestone 3 grounded-RAG dataset unchanged. Reachable
identically via `python -m app.rag.evaluate` (see `test_cli_aliases.py`
for the alias identity check) or `python -m app.evaluation.rag_evaluator`.
"""

import json

import app.evaluation.rag_evaluator as rag_evaluator
from app.config.settings import IngestionSettings, RagSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
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


def _build_workflow_engine(tmp_path):
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


def test_category_workflows_runs_the_workflow_evaluator(monkeypatch, capsys, tmp_path):
    engine = _build_workflow_engine(tmp_path)
    monkeypatch.setattr("app.workflows.engine.build_default_workflow_engine", lambda *a, **kw: engine)

    # A minimal one-case dataset so this test doesn't depend on the real
    # examples/workflows fixtures or the real (large) knowledge base.
    input_file = tmp_path / "input.json"
    input_file.write_text(
        json.dumps({
            "release_name": "r", "services_affected": ["s"], "business_impact": "b",
            "deployment_strategy": "canary", "rollback_plan": "yes",
        }),
        encoding="utf-8",
    )
    dataset_file = tmp_path / "dataset.json"
    dataset_file.write_text(
        json.dumps([{
            "id": "t1", "workflow_id": "production_readiness_review", "input_file": str(input_file),
        }]),
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["app.rag.evaluate", "--category", "workflows", "--dataset", str(dataset_file)])
    rag_evaluator.main()

    output = capsys.readouterr().out
    assert "Milestone 6 workflow evaluation" in output
    assert "workflow_completion_rate" in output


def test_default_category_still_runs_the_rag_evaluator(monkeypatch, capsys, tmp_path):
    # No real KB/index needed -- an empty dataset exercises the rag path
    # end to end (build_default_rag_service + zero cases) without
    # depending on the real knowledge base being indexed. --dataset is
    # used as-is (no PROJECT_ROOT join), so a tmp_path file works directly.
    empty_dataset = tmp_path / "empty_dataset.json"
    empty_dataset.write_text(json.dumps([]), encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["app.rag.evaluate", "--dataset", str(empty_dataset)])
    rag_evaluator.main()

    output = capsys.readouterr().out
    assert "Milestone 3 evaluation" in output
    assert "0/0 case(s) passed" in output
