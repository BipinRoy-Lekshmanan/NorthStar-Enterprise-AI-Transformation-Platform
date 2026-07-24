"""End-to-end advisor tests: real RagService (Milestone 1-3 infrastructure,
untouched), FakeModelProvider, a small two-document fixture KB -- no
network, no API key.
"""

from app.agents.registry import get_advisor
from app.config.settings import IngestionSettings, RagSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.ingestion.pipeline import IngestionPipeline
from app.rag.context_builder import ContextBuilder
from app.rag.pipeline import RagService
from app.rag.retriever import Retriever
from app.services.llm_service import FakeModelProvider


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


def _build_rag_service(tmp_path) -> RagService:
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
    return RagService(retriever, context_builder, FakeModelProvider(), _rag_settings(), default_top_k=10)


def test_filtered_advisor_only_retrieves_from_its_own_document(tmp_path):
    service = _build_rag_service(tmp_path)
    advisor = get_advisor("testing")

    answer = advisor.ask(service, "What requirements apply here?")

    assert answer.sufficient_context is True
    source_files = {c.source_file for c in answer.citations}
    assert source_files <= {"14_Testing_Strategy.md"}
    assert "13_DevSecOps_Standards.md" not in source_files


def test_unfiltered_advisor_can_retrieve_across_documents(tmp_path):
    service = _build_rag_service(tmp_path)
    advisor = get_advisor("security")

    # Ask something that could plausibly match either seeded document.
    answer = advisor.ask(service, "What requirements apply here?")

    assert answer.sufficient_context is True
    # No assertion on *which* document -- the point is nothing filtered it out.
    assert answer.citations


def test_advisor_diagnostics_carry_the_advisor_prompt_version(tmp_path):
    service = _build_rag_service(tmp_path)
    advisor = get_advisor("devsecops")

    answer = advisor.ask(service, "What secure coding requirements apply?")

    assert answer.diagnostics.prompt_version == advisor.prompt_version
    assert answer.diagnostics.prompt_version.endswith("+devsecops-v1")


def test_advisor_system_prompt_actually_reaches_the_model(tmp_path):
    service = _build_rag_service(tmp_path)
    advisor = get_advisor("security")  # unfiltered -- guaranteed to find content in the fixture KB
    captured_prompts = []

    answer = advisor.ask(
        service, "What requirements apply here?", on_prompt_built=captured_prompts.append
    )

    assert answer.sufficient_context is True
    assert len(captured_prompts) == 1
    assert captured_prompts[0].system == advisor.system_prompt


def test_advisor_insufficient_context_short_circuits_same_as_plain_service(tmp_path):
    service = _build_rag_service(tmp_path)
    # A threshold no retrieval score in this tiny fixture KB can clear.
    strict_context_builder = ContextBuilder(
        max_characters=6000, max_chunks=6, min_score=0.0,
        insufficient_min_results=1, insufficient_min_score=0.99,
    )
    strict_service = RagService(
        service.retriever, strict_context_builder, FakeModelProvider(), _rag_settings(), default_top_k=10
    )
    advisor = get_advisor("testing")

    answer = advisor.ask(strict_service, "What requirements apply here?")

    assert answer.sufficient_context is False
    assert answer.citations == []
    assert answer.diagnostics.model_provider is None


def test_filtered_advisor_with_no_matching_document_is_insufficient_not_a_crash(tmp_path):
    """The fixture KB has no NLC-ENG-002 document, so the Architecture
    advisor's default filter matches nothing -- it must report
    insufficient context, never fabricate an answer from unrelated docs."""
    service = _build_rag_service(tmp_path)
    advisor = get_advisor("architecture")

    answer = advisor.ask(service, "What requirements apply here?")

    assert answer.sufficient_context is False
    assert answer.citations == []


def test_plain_service_ask_unaffected_by_advisor_module_existing(tmp_path):
    """Regression check: calling RagService.ask() directly (no advisor)
    still produces the exact same shape of result as Milestone 3."""
    service = _build_rag_service(tmp_path)

    answer = service.ask("What requirements apply here?")

    assert answer.diagnostics.prompt_version == "rag-system-v1"
    assert answer.sufficient_context is True
