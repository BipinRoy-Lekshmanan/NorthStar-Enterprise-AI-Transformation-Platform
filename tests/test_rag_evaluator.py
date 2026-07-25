"""Tests for `app.evaluation.rag_evaluator` (Milestone 8 focus: per-case
failure isolation in `run_evaluation()` -- no dedicated test file
existed for this evaluator before this one, confirmed by a repo search;
Milestone 3's coverage was only indirect, via `test_evaluate_cli.py`).
"""

from __future__ import annotations

from app.config.settings import IngestionSettings, RagSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.evaluation.rag_evaluator import EvalCase, run_evaluation
from app.ingestion.pipeline import IngestionPipeline
from app.rag.context_builder import ContextBuilder
from app.rag.pipeline import RagService
from app.rag.retriever import Retriever
from app.services.llm_service import FakeModelProvider, ModelUnavailableError


class _FailsForMarkerProvider:
    """Fails only for questions containing "BROKEN" -- lets one test
    exercise a genuine mix of a passing case and a raising case."""

    def __init__(self, delegate):
        self._delegate = delegate

    def generate(self, *, system_prompt, user_prompt, temperature=0.0, max_tokens=None):
        if "BROKEN" in user_prompt:
            raise ModelUnavailableError("simulated outage")
        return self._delegate.generate(
            system_prompt=system_prompt, user_prompt=user_prompt, temperature=temperature, max_tokens=max_tokens,
        )


def _rag_settings(**overrides):
    defaults = dict(
        llm_provider="fake", llm_model="fake-echo-v1", llm_api_key=None,
        llm_temperature=0.0, llm_max_output_tokens=1024, llm_timeout_seconds=30.0,
        context_max_characters=6000, context_max_chunks=6, context_min_score=0.0,
        max_question_length=2000, insufficient_context_min_results=1, insufficient_context_min_score=0.0,
    )
    defaults.update(overrides)
    return RagSettings(**defaults)


def _build_service(tmp_path, llm):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "14_Testing_Strategy.md").write_text(
        "---\ndocument_id: NLC-ENG-005\ntitle: Testing Strategy\n---\n\n# Testing Strategy\n\n## Coverage\n\n"
        + ("Unit and integration test coverage is required before every release. " * 15),
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
    return RagService(retriever, context_builder, llm, _rag_settings(), default_top_k=10)


def _case(case_id, question):
    return EvalCase(
        id=case_id, question=question, expected_documents=[], must_include_concepts=[],
        requires_citation=False, expected_sufficient_context=True,
    )


def test_a_raising_case_is_isolated_and_does_not_lose_other_results(tmp_path):
    service = _build_service(tmp_path, _FailsForMarkerProvider(FakeModelProvider()))
    good_case = _case("good", "What testing evidence is required?")
    broken_case = _case("broken", "BROKEN marker question")

    results = run_evaluation(service, [good_case, broken_case])

    assert [r.case_id for r in results] == ["good", "broken"]
    good, broken = results
    assert good.passed is True
    assert broken.passed is False
    assert broken.checks == {}
    assert broken.notes and "exception" in broken.notes[0].lower()


def test_every_case_raising_still_returns_one_result_per_case(tmp_path):
    service = _build_service(tmp_path, _FailsForMarkerProvider(FakeModelProvider()))
    cases = [_case("a", "BROKEN one"), _case("b", "BROKEN two"), _case("c", "BROKEN three")]

    results = run_evaluation(service, cases)

    assert [r.case_id for r in results] == ["a", "b", "c"]
    assert all(r.passed is False for r in results)
