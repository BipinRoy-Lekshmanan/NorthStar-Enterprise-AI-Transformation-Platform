"""Tests for graceful degradation in `app.api.services.query_service`
(Milestone 8): when the model provider is unavailable, `ask_manual`/
`ask_auto` fall back to retrieval-only excerpts with a clear warning,
rather than either a hard 502 or a fabricated answer. Uses a small fake
provider that always raises `ModelUnavailableError` -- a real,
independent failure mode from retrieval, which keeps working since it
never touches the model provider.
"""

from __future__ import annotations

from app.api.services.query_service import QueryFilters, ask_auto, ask_manual
from app.config.settings import IngestionSettings, RagSettings, RouterSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.ingestion.pipeline import IngestionPipeline
from app.rag.context_builder import ContextBuilder
from app.rag.pipeline import RagService
from app.rag.retriever import Retriever
from app.services.llm_service import ModelUnavailableError


class _AlwaysUnavailableModelProvider:
    def generate(self, *, system_prompt, user_prompt, temperature=0.0, max_tokens=None):
        raise ModelUnavailableError("simulated outage")


def _rag_settings(**overrides):
    defaults = dict(
        llm_provider="fake", llm_model="fake-echo-v1", llm_api_key=None,
        llm_temperature=0.0, llm_max_output_tokens=1024, llm_timeout_seconds=30.0,
        context_max_characters=6000, context_max_chunks=6, context_min_score=0.0,
        max_question_length=2000, insufficient_context_min_results=1, insufficient_context_min_score=0.0,
    )
    defaults.update(overrides)
    return RagSettings(**defaults)


def _router_settings(**overrides):
    defaults = dict(
        router_retrieval_top_k=12, router_min_confidence=0.15,
        router_supporting_min_ratio=0.4, router_max_supporting_advisors=2,
        router_retrieval_weight=0.6, router_keyword_weight=0.4,
    )
    defaults.update(overrides)
    return RouterSettings(**defaults)


def _build_service(tmp_path):
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
    return RagService(retriever, context_builder, _AlwaysUnavailableModelProvider(), _rag_settings(), default_top_k=10)


def test_ask_manual_degrades_to_retrieval_only_when_provider_unavailable(tmp_path):
    service = _build_service(tmp_path)
    result = ask_manual(service, "What testing evidence is required?", "testing", QueryFilters())

    assert result.degraded is True
    assert result.sufficient_context is False
    assert result.citations == []
    assert result.retrieved_context  # real excerpts, not empty
    assert any("unavailable" in w.lower() for w in result.warnings)
    assert "generated answer is currently unavailable" in result.answer.lower()


def test_ask_manual_degraded_excerpts_are_real_kb_content(tmp_path):
    service = _build_service(tmp_path)
    result = ask_manual(service, "What testing evidence is required?", "testing", QueryFilters())

    assert result.retrieved_context is not None
    assert any("test" in chunk.text.lower() for chunk in result.retrieved_context)


def test_ask_auto_degrades_to_retrieval_only_when_provider_unavailable(tmp_path):
    service = _build_service(tmp_path)
    result = ask_auto(service, _rag_settings(), _router_settings(), "What testing evidence is required?", QueryFilters())

    assert result.degraded is True
    assert result.sufficient_context is False
    assert result.citations == []
    assert result.retrieved_context
