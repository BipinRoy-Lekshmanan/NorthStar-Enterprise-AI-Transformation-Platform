import pytest

from app.config.settings import IngestionSettings, RagSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.ingestion.pipeline import IngestionPipeline
from app.rag.context_builder import ContextBuilder
from app.rag.pipeline import QuestionValidationError, RagService
from app.rag.retriever import Retriever
from app.services.llm_service import FakeModelProvider, ModelProviderError


def _rag_settings(**overrides) -> RagSettings:
    defaults = dict(
        llm_provider="fake", llm_model="fake-echo-v1", llm_api_key=None,
        llm_temperature=0.0, llm_max_output_tokens=1024, llm_timeout_seconds=30.0,
        context_max_characters=6000, context_max_chunks=6, context_min_score=0.0,
        max_question_length=2000,
        insufficient_context_min_results=1, insufficient_context_min_score=0.15,
    )
    defaults.update(overrides)
    return RagSettings(**defaults)


def _seed_kb(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "16_Incident_Management.md").write_text(
        "---\ndocument_id: NLC-ENG-007\ntitle: Incident Management\n---\n\n"
        "# Incident Management\n\n## Major Incident Response\n\n"
        + ("Sev1 incidents require an incident commander and a dedicated war room. " * 15),
        encoding="utf-8",
    )
    return kb_dir


def _build_service(tmp_path, llm=None, rag_settings=None, min_score=0.0, insufficient_min_score=0.15):
    kb_dir = _seed_kb(tmp_path)
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
        max_characters=6000, max_chunks=6, min_score=min_score,
        insufficient_min_results=1, insufficient_min_score=insufficient_min_score,
    )
    llm = llm or FakeModelProvider()
    settings = rag_settings or _rag_settings()

    return RagService(retriever, context_builder, llm, settings, default_top_k=5), llm


def test_sufficient_context_produces_grounded_answer(tmp_path):
    service, llm = _build_service(tmp_path)

    answer = service.ask("How should a Sev1 incident be handled?")

    assert answer.sufficient_context is True
    assert answer.citations
    assert answer.citations[0].source_path == "16_Incident_Management.md"
    assert answer.diagnostics.model_provider == "fake"
    assert answer.diagnostics.context_chunk_count > 0
    assert llm.call_count == 1


def test_insufficient_context_does_not_call_the_model(tmp_path):
    service, llm = _build_service(tmp_path, insufficient_min_score=0.9)

    answer = service.ask("How should a Sev1 incident be handled?")

    assert answer.sufficient_context is False
    assert "could not find enough information" in answer.answer.lower()
    assert answer.citations == []
    assert llm.call_count == 0
    assert answer.diagnostics.model_provider is None


def test_no_retrieval_results_is_insufficient(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "empty.md").write_text("# Empty\n", encoding="utf-8")
    ingestion_settings = IngestionSettings(
        knowledge_base_dirs=(kb_dir,), supported_extensions=(".md",),
        chunk_size=500, chunk_overlap=50, log_level="INFO", output_dir=tmp_path / "processed",
    )
    provider = LocalHashingEmbeddingProvider(dimensions=64)
    store = LocalVectorStore(tmp_path / "store")
    # No indexing at all -> store is empty -> zero retrieval results
    retriever = Retriever(provider, store)
    context_builder = ContextBuilder(
        max_characters=6000, max_chunks=6, min_score=0.0,
        insufficient_min_results=1, insufficient_min_score=0.15,
    )
    llm = FakeModelProvider()
    service = RagService(retriever, context_builder, llm, _rag_settings(), default_top_k=5)

    answer = service.ask("Anything?")

    assert answer.sufficient_context is False
    assert llm.call_count == 0


def test_provider_failure_propagates(tmp_path):
    class FailingProvider:
        def generate(self, **kwargs):
            raise ModelProviderError("simulated outage")

    service, _ = _build_service(tmp_path, llm=FailingProvider())

    with pytest.raises(ModelProviderError):
        service.ask("How should a Sev1 incident be handled?")


def test_empty_question_raises_validation_error(tmp_path):
    service, _ = _build_service(tmp_path)

    with pytest.raises(QuestionValidationError):
        service.ask("   ")


def test_overly_long_question_raises_validation_error(tmp_path):
    service, _ = _build_service(tmp_path, rag_settings=_rag_settings(max_question_length=50))

    with pytest.raises(QuestionValidationError):
        service.ask("x" * 100)


def test_on_context_built_hook_invoked(tmp_path):
    service, _ = _build_service(tmp_path)
    captured = []

    service.ask("How should a Sev1 incident be handled?", on_context_built=captured.append)

    assert len(captured) == 1
    assert captured[0].sufficient is True


def test_on_prompt_built_hook_invoked_only_when_sufficient(tmp_path):
    service, _ = _build_service(tmp_path, insufficient_min_score=0.9)
    captured = []

    service.ask("How should a Sev1 incident be handled?", on_prompt_built=captured.append)

    assert captured == []  # insufficient context -> prompt never built


def test_diagnostics_request_id_is_unique_per_call(tmp_path):
    service, _ = _build_service(tmp_path)

    first = service.ask("How should a Sev1 incident be handled?")
    second = service.ask("How should a Sev1 incident be handled?")

    assert first.diagnostics.request_id != second.diagnostics.request_id


def test_filters_are_forwarded_to_retrieval(tmp_path):
    service, _ = _build_service(tmp_path)

    answer = service.ask(
        "How should a Sev1 incident be handled?",
        filters={"document_id": "NLC-ENG-007"},
    )

    assert answer.sufficient_context is True
