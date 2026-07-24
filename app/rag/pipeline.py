"""Grounded RAG orchestration.

Question -> validate -> retrieve -> build bounded context -> (insufficient?
short-circuit) -> build prompt -> call the language model -> parse
citations -> RagAnswer.

Each step is delegated to its own module (`app.rag.retriever`,
`app.rag.context_builder`, `app.config.prompt_config`,
`app.services.llm_service`, `app.rag.citation_engine`) -- this file only
sequences them and assembles the final typed answer + diagnostics.
`QuestionValidationError` and any `ModelProviderError` from the language
model propagate out of `ask()` rather than being disguised as content;
callers (the CLI) decide how to present those.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from app.config.prompt_config import RagPrompt, build_prompt
from app.config.settings import RagSettings, RetrievalSettings
from app.embeddings.indexer import build_provider_and_store
from app.models.query import RetrievalQuery
from app.models.response import RagAnswer, RagDiagnostics, RetrievalResponse
from app.rag.citation_engine import build_citations, parse_citation_ids
from app.rag.context_builder import ContextBuilder, ContextBuildResult
from app.rag.retriever import Retriever
from app.services.llm_service import FakeModelProvider, LanguageModelProvider
from app.services.openai_llm_provider import OpenAIModelProvider

logger = logging.getLogger(__name__)

_INSUFFICIENCY_MESSAGES = {
    "no_results": "No relevant documents were found in the Northstar knowledge base.",
    "low_relevance": "The most relevant documents found were not closely related to this question.",
    "no_usable_context": "Retrieved documents did not contain usable content for this question.",
}


class QuestionValidationError(ValueError):
    """Raised when a question is empty or exceeds the configured length limit."""


class RagService:
    def __init__(
        self,
        retriever: Retriever,
        context_builder: ContextBuilder,
        llm: LanguageModelProvider,
        settings: RagSettings,
        default_top_k: int = 5,
    ):
        self._retriever = retriever
        self._context_builder = context_builder
        self._llm = llm
        self._settings = settings
        self._default_top_k = default_top_k

    @property
    def retriever(self) -> Retriever:
        """Exposes the underlying `Retriever` for tooling (e.g. the evaluator) that
        needs raw retrieval results independent of citation/generation behavior."""
        return self._retriever

    def ask(
        self,
        question: str,
        *,
        top_k: int | None = None,
        filters: dict[str, str] | None = None,
        system_prompt: str | None = None,
        prompt_version: str | None = None,
        on_context_built: Callable[[ContextBuildResult], None] | None = None,
        on_prompt_built: Callable[[RagPrompt], None] | None = None,
    ) -> RagAnswer:
        request_start = time.perf_counter()
        request_id = uuid.uuid4().hex[:12]

        self._validate_question(question)

        query = RetrievalQuery(text=question, top_k=top_k or self._default_top_k, filters=filters or {})
        retrieval_start = time.perf_counter()
        retrieval_response = self._retriever.retrieve(query)
        retrieval_duration_ms = (time.perf_counter() - retrieval_start) * 1000

        context_result = self._context_builder.build(retrieval_response.results)
        if on_context_built is not None:
            on_context_built(context_result)

        if not context_result.sufficient:
            total_duration_ms = (time.perf_counter() - request_start) * 1000
            answer = self._insufficient_context_answer(
                question, request_id, retrieval_response, context_result,
                retrieval_duration_ms, total_duration_ms,
            )
            logger.info(
                "RagService.ask request_id=%s sufficient=False reason=%s total_duration_ms=%.1f",
                request_id, context_result.insufficiency_reason, total_duration_ms,
            )
            return answer

        prompt = build_prompt(
            question, context_result.blocks, system_prompt=system_prompt, prompt_version=prompt_version
        )
        if on_prompt_built is not None:
            on_prompt_built(prompt)

        model_response = self._llm.generate(
            system_prompt=prompt.system,
            user_prompt=prompt.user,
            temperature=self._settings.llm_temperature,
            max_tokens=self._settings.llm_max_output_tokens,
        )

        valid_ids = {block.source_id for block in context_result.blocks}
        cited_ids, warnings = parse_citation_ids(model_response.text, valid_ids)
        citations = build_citations(cited_ids, context_result.blocks)

        total_duration_ms = (time.perf_counter() - request_start) * 1000
        diagnostics = RagDiagnostics(
            request_id=request_id,
            retrieval_duration_ms=retrieval_duration_ms,
            embed_duration_ms=retrieval_response.diagnostics.embed_latency_ms,
            search_duration_ms=retrieval_response.diagnostics.search_latency_ms,
            retrieved_chunk_count=len(retrieval_response.results),
            context_chunk_count=len(context_result.blocks),
            chunks_excluded=context_result.excluded_count,
            highest_retrieval_score=context_result.highest_score,
            model_provider=model_response.provider,
            model_name=model_response.model,
            model_latency_ms=model_response.latency_ms,
            input_tokens=model_response.input_tokens,
            output_tokens=model_response.output_tokens,
            total_duration_ms=total_duration_ms,
            prompt_version=prompt.version,
        )

        logger.info(
            "RagService.ask request_id=%s sufficient=True chunks=%d citations=%d warnings=%d "
            "provider=%s model=%s total_duration_ms=%.1f",
            request_id, len(context_result.blocks), len(citations), len(warnings),
            model_response.provider, model_response.model, total_duration_ms,
        )

        return RagAnswer(
            question=question,
            answer=model_response.text,
            citations=citations,
            sufficient_context=True,
            warnings=warnings,
            diagnostics=diagnostics,
        )

    def _validate_question(self, question: str) -> None:
        stripped = question.strip()
        if not stripped:
            raise QuestionValidationError("Question must not be empty.")
        if len(stripped) > self._settings.max_question_length:
            raise QuestionValidationError(
                f"Question is too long ({len(stripped)} chars); "
                f"maximum is {self._settings.max_question_length}."
            )

    @staticmethod
    def _insufficient_context_answer(
        question: str,
        request_id: str,
        retrieval_response: RetrievalResponse,
        context_result: ContextBuildResult,
        retrieval_duration_ms: float,
        total_duration_ms: float,
    ) -> RagAnswer:
        reason_text = _INSUFFICIENCY_MESSAGES.get(
            context_result.insufficiency_reason or "", "Insufficient relevant context was found."
        )
        score_text = (
            f"{context_result.highest_score:.3f}" if context_result.highest_score is not None else "n/a"
        )
        answer_text = (
            "I could not find enough information in the Northstar knowledge base to answer this reliably.\n\n"
            f"{reason_text}\n"
            f"Documents searched: {retrieval_response.diagnostics.total_indexed_chunks} indexed chunks. "
            f"Retrieved results: {len(retrieval_response.results)}. "
            f"Highest relevance score: {score_text}.\n"
            "Consider rephrasing the question with more specific Northstar terminology. "
            "This response is based solely on the Northstar knowledge base; general industry "
            "guidance was not used."
        )

        diagnostics = RagDiagnostics(
            request_id=request_id,
            retrieval_duration_ms=retrieval_duration_ms,
            embed_duration_ms=retrieval_response.diagnostics.embed_latency_ms,
            search_duration_ms=retrieval_response.diagnostics.search_latency_ms,
            retrieved_chunk_count=len(retrieval_response.results),
            context_chunk_count=0,
            chunks_excluded=context_result.excluded_count,
            highest_retrieval_score=context_result.highest_score,
            model_provider=None,
            model_name=None,
            model_latency_ms=None,
            input_tokens=None,
            output_tokens=None,
            total_duration_ms=total_duration_ms,
            prompt_version=None,
        )

        return RagAnswer(
            question=question,
            answer=answer_text,
            citations=[],
            sufficient_context=False,
            warnings=[],
            diagnostics=diagnostics,
        )


def build_default_rag_service(
    rag_settings: RagSettings | None = None,
    retrieval_settings: RetrievalSettings | None = None,
) -> RagService:
    rag_settings = rag_settings or RagSettings.from_env()
    retrieval_settings = retrieval_settings or RetrievalSettings.from_env()

    provider, store = build_provider_and_store(retrieval_settings)
    retriever = Retriever(provider, store)

    context_builder = ContextBuilder(
        max_characters=rag_settings.context_max_characters,
        max_chunks=rag_settings.context_max_chunks,
        min_score=rag_settings.context_min_score,
        insufficient_min_results=rag_settings.insufficient_context_min_results,
        insufficient_min_score=rag_settings.insufficient_context_min_score,
    )

    llm = _build_llm_provider(rag_settings)

    return RagService(
        retriever, context_builder, llm, rag_settings, default_top_k=retrieval_settings.retrieval_top_k
    )


def _build_llm_provider(settings: RagSettings) -> LanguageModelProvider:
    if settings.llm_provider == "openai":
        assert settings.llm_api_key is not None  # enforced by RagSettings.validate()
        return OpenAIModelProvider(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout_seconds,
        )
    return FakeModelProvider(model=settings.llm_model)
