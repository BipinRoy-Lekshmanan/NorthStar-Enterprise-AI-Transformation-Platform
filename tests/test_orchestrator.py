"""Tests for `app.agents.orchestrator.AdvisorOrchestrator` -- bounded
multi-advisor execution + a single synthesis call over already-grounded
advisor answers. Real `RagService` and real `Advisor` definitions
(Milestone 1-4 infrastructure, untouched), `FakeModelProvider`, a small
fixture KB -- no network, no API key.

Routing itself is exercised separately in `tests/test_router.py`; here a
stub router with a fixed `RoutingDecision` isolates orchestration
(execution ordering, LLM call bounding, citation dedup, short-circuit
behavior) from routing signal computation.
"""

from app.agents.orchestrator import AdvisorOrchestrator
from app.agents.router import RoutingDecision
from app.config.settings import IngestionSettings, RagSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.ingestion.pipeline import IngestionPipeline
from app.rag.context_builder import ContextBuilder
from app.rag.pipeline import RagService
from app.rag.retriever import Retriever
from app.services.llm_service import FakeModelProvider


class _StubRouter:
    """Fixed-decision stand-in for `AdvisorRouter` -- isolates orchestration
    behavior from routing signal computation, which has its own tests."""

    def __init__(self, decision: RoutingDecision):
        self._decision = decision

    def route(self, question: str) -> RoutingDecision:
        return self._decision


def _rag_settings(**overrides) -> RagSettings:
    defaults = dict(
        llm_provider="fake", llm_model="fake-echo-v1", llm_api_key=None,
        llm_temperature=0.0, llm_max_output_tokens=1024, llm_timeout_seconds=30.0,
        context_max_characters=6000, context_max_chunks=6, context_min_score=0.0,
        max_question_length=2000,
        insufficient_context_min_results=1, insufficient_context_min_score=0.0,
    )
    defaults.update(overrides)
    return RagSettings(**defaults)


def _seed_two_document_kb(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "14_Testing_Strategy.md").write_text(
        "---\ndocument_id: NLC-ENG-005\ntitle: Testing Strategy\n---\n\n"
        "# Testing Strategy\n\n## Test Coverage Requirements\n\n"
        + ("Unit and integration test coverage is required before release. " * 15),
        encoding="utf-8",
    )
    (kb_dir / "13_DevSecOps_Standards.md").write_text(
        "---\ndocument_id: NLC-ENG-004\ntitle: DevSecOps Standards\n---\n\n"
        "# DevSecOps Standards\n\n## Secure Coding Requirements\n\n"
        + ("Secure coding requires input validation and dependency scanning. " * 15),
        encoding="utf-8",
    )
    return kb_dir


def _build_service(tmp_path, llm) -> RagService:
    kb_dir = _seed_two_document_kb(tmp_path)
    ingestion_settings = IngestionSettings(
        knowledge_base_dirs=(kb_dir,), supported_extensions=(".md",),
        chunk_size=500, chunk_overlap=50, log_level="INFO", output_dir=tmp_path / "processed",
    )
    pipeline = IngestionPipeline(settings=ingestion_settings)

    provider = LocalHashingEmbeddingProvider(dimensions=128)
    store = LocalVectorStore(tmp_path / "store")
    Indexer(provider, store).index_from_pipeline(pipeline)

    retriever = Retriever(provider, store)
    context_builder = ContextBuilder(
        max_characters=6000, max_chunks=6, min_score=0.0,
        insufficient_min_results=1, insufficient_min_score=0.0,
    )
    return RagService(retriever, context_builder, llm, _rag_settings(), default_top_k=10)


def _decision(primary: str, supporting: list[str]) -> RoutingDecision:
    return RoutingDecision(
        primary_advisor=primary,
        supporting_advisors=supporting,
        confidence=0.9,
        rationale="test rationale",
        detected_domains=[],
        fallback_used=False,
    )


def test_single_advisor_path_has_no_synthesis_and_verbatim_answer(tmp_path):
    llm = FakeModelProvider()
    service = _build_service(tmp_path, llm)
    orchestrator = AdvisorOrchestrator(service, _StubRouter(_decision("testing", [])), llm, _rag_settings())

    response = orchestrator.ask("What requirements apply here?")

    assert response.synthesized is False
    assert response.synthesis_provider is None
    assert response.synthesis_model is None
    assert response.synthesis_latency_ms is None
    assert response.supporting_answers == []
    assert response.answer == response.primary_answer.answer
    assert response.citations == response.primary_answer.citations
    assert llm.call_count == 1  # only the primary advisor's call


def test_multi_advisor_path_synthesizes_exactly_once(tmp_path):
    llm = FakeModelProvider()
    service = _build_service(tmp_path, llm)
    decision = _decision("testing", ["devsecops"])
    orchestrator = AdvisorOrchestrator(service, _StubRouter(decision), llm, _rag_settings())

    response = orchestrator.ask("What requirements apply here?")

    assert response.synthesized is True
    assert response.synthesis_provider == "fake"
    assert response.synthesis_model == "fake-echo-v1"
    assert response.synthesis_latency_ms is not None
    assert len(response.supporting_answers) == 1
    assert llm.call_count == 3  # primary + 1 supporting + 1 synthesis


def test_multi_advisor_citations_are_deduped_union(tmp_path):
    llm = FakeModelProvider()
    service = _build_service(tmp_path, llm)
    decision = _decision("testing", ["devsecops"])
    orchestrator = AdvisorOrchestrator(service, _StubRouter(decision), llm, _rag_settings())

    response = orchestrator.ask("What requirements apply here?")

    primary_ids = {c.chunk_id for c in response.primary_answer.citations}
    supporting_ids = {c.chunk_id for c in response.supporting_answers[0].citations}
    result_ids = [c.chunk_id for c in response.citations]

    assert set(result_ids) == primary_ids | supporting_ids
    assert len(result_ids) == len(set(result_ids))  # no duplicates
    # Never re-derived from synthesis text -- every citation traces to a real advisor answer.
    assert all(cid in (primary_ids | supporting_ids) for cid in result_ids)


def test_primary_insufficient_context_short_circuits_before_any_llm_call(tmp_path):
    llm = FakeModelProvider()
    service = _build_service(tmp_path, llm)
    # "architecture"'s default document filter (NLC-ENG-002) matches nothing in this
    # 2-document fixture KB, so its RagAnswer must be insufficient_context=False.
    decision = _decision("architecture", ["devsecops"])
    orchestrator = AdvisorOrchestrator(service, _StubRouter(decision), llm, _rag_settings())

    response = orchestrator.ask("What requirements apply here?")

    assert response.primary_answer.sufficient_context is False
    assert response.supporting_answers == []
    assert response.synthesized is False
    assert response.citations == []
    assert llm.call_count == 0  # insufficient-context short-circuit happens before any model call


def test_warnings_aggregate_from_primary_and_supporting(tmp_path):
    llm = FakeModelProvider(canned_answer="This answer cites nothing.")
    service = _build_service(tmp_path, llm)
    decision = _decision("testing", ["devsecops"])
    orchestrator = AdvisorOrchestrator(service, _StubRouter(decision), llm, _rag_settings())

    response = orchestrator.ask("What requirements apply here?")

    assert "Model did not cite any source." in response.primary_answer.warnings
    assert "Model did not cite any source." in response.supporting_answers[0].warnings
    assert response.warnings.count("Model did not cite any source.") == 2
