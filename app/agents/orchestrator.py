"""Bounded multi-advisor execution and synthesis (Milestone 5).

`AdvisorOrchestrator.ask()` sequences: route -> call primary advisor ->
(short-circuit if primary lacks sufficient context) -> call supporting
advisors -> (no supporting advisors? done) -> one bounded synthesis call
over the already-grounded advisor answers.

This is intentionally not an agent loop: every step is a single,
predetermined call into existing Milestone 1-4 infrastructure
(`Advisor.ask()` -> `RagService.ask()`), the number of calls is bounded
by construction (1 primary + at most `router_max_supporting_advisors`
supporting + at most 1 synthesis), and there is no branching driven by
model output -- the model never chooses what to call next.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.agents.base_agent import Advisor
from app.agents.registry import get_advisor, list_advisors
from app.agents.router import AdvisorRouter, RoutingDecision
from app.config.prompt_config import SynthesisInput, build_synthesis_prompt
from app.config.settings import RagSettings, RetrievalSettings, RouterSettings
from app.models.citation import Citation
from app.models.response import RagAnswer
from app.rag.pipeline import RagService, build_default_rag_service
from app.services.llm_service import LanguageModelProvider


@dataclass(frozen=True)
class ConsolidatedAdvisorResponse:
    question: str
    routing: RoutingDecision
    primary_answer: RagAnswer
    supporting_answers: list[RagAnswer]
    answer: str
    citations: list[Citation]
    warnings: list[str]
    synthesized: bool
    synthesis_provider: str | None
    synthesis_model: str | None
    synthesis_latency_ms: float | None
    total_duration_ms: float


class AdvisorOrchestrator:
    def __init__(
        self,
        service: RagService,
        router: AdvisorRouter,
        llm: LanguageModelProvider,
        rag_settings: RagSettings,
    ):
        self._service = service
        self._router = router
        self._llm = llm
        self._rag_settings = rag_settings

    def ask(self, question: str) -> ConsolidatedAdvisorResponse:
        request_start = time.perf_counter()

        routing = self._router.route(question)
        primary_advisor = get_advisor(routing.primary_advisor)
        primary_answer = primary_advisor.ask(self._service, question)

        warnings = list(primary_answer.warnings)

        if not primary_answer.sufficient_context:
            return self._unsynthesized_response(
                question, routing, primary_answer, [], warnings, request_start
            )

        supporting_answers: list[RagAnswer] = []
        for advisor_id in routing.supporting_advisors:
            supporting_advisor = get_advisor(advisor_id)
            supporting_answer = supporting_advisor.ask(self._service, question)
            supporting_answers.append(supporting_answer)
            warnings.extend(supporting_answer.warnings)

        if not supporting_answers:
            return self._unsynthesized_response(
                question, routing, primary_answer, [], warnings, request_start
            )

        return self._synthesized_response(
            question, routing, primary_advisor, primary_answer, supporting_answers, warnings, request_start
        )

    def _unsynthesized_response(
        self,
        question: str,
        routing: RoutingDecision,
        primary_answer: RagAnswer,
        supporting_answers: list[RagAnswer],
        warnings: list[str],
        request_start: float,
    ) -> ConsolidatedAdvisorResponse:
        total_duration_ms = (time.perf_counter() - request_start) * 1000
        return ConsolidatedAdvisorResponse(
            question=question,
            routing=routing,
            primary_answer=primary_answer,
            supporting_answers=supporting_answers,
            answer=primary_answer.answer,
            citations=list(primary_answer.citations),
            warnings=warnings,
            synthesized=False,
            synthesis_provider=None,
            synthesis_model=None,
            synthesis_latency_ms=None,
            total_duration_ms=total_duration_ms,
        )

    def _synthesized_response(
        self,
        question: str,
        routing: RoutingDecision,
        primary_advisor: Advisor,
        primary_answer: RagAnswer,
        supporting_answers: list[RagAnswer],
        warnings: list[str],
        request_start: float,
    ) -> ConsolidatedAdvisorResponse:
        sections = [SynthesisInput(primary_advisor.display_name, "primary", primary_answer.answer)]
        for advisor_id, answer in zip(routing.supporting_advisors, supporting_answers):
            advisor = get_advisor(advisor_id)
            sections.append(SynthesisInput(advisor.display_name, "supporting", answer.answer))

        prompt = build_synthesis_prompt(question, sections)
        model_response = self._llm.generate(
            system_prompt=prompt.system,
            user_prompt=prompt.user,
            temperature=self._rag_settings.llm_temperature,
            max_tokens=self._rag_settings.llm_max_output_tokens,
        )

        citations = _dedupe_citations([primary_answer, *supporting_answers])
        total_duration_ms = (time.perf_counter() - request_start) * 1000

        return ConsolidatedAdvisorResponse(
            question=question,
            routing=routing,
            primary_answer=primary_answer,
            supporting_answers=supporting_answers,
            answer=model_response.text,
            citations=citations,
            warnings=warnings,
            synthesized=True,
            synthesis_provider=model_response.provider,
            synthesis_model=model_response.model,
            synthesis_latency_ms=model_response.latency_ms,
            total_duration_ms=total_duration_ms,
        )


def _dedupe_citations(answers: list[RagAnswer]) -> list[Citation]:
    """Union citations from every advisor answer, deduped by `chunk_id`,
    order-preserving. Never re-derived from synthesis output text, so
    nothing the synthesis step writes can fabricate a citation."""
    seen: set[str] = set()
    result: list[Citation] = []
    for answer in answers:
        for citation in answer.citations:
            if citation.chunk_id in seen:
                continue
            seen.add(citation.chunk_id)
            result.append(citation)
    return result


def build_default_orchestrator(
    rag_settings: RagSettings | None = None,
    retrieval_settings: RetrievalSettings | None = None,
    router_settings: RouterSettings | None = None,
) -> AdvisorOrchestrator:
    rag_settings = rag_settings or RagSettings.from_env()
    service = build_default_rag_service(rag_settings, retrieval_settings)
    router = AdvisorRouter(service.retriever, list_advisors(), router_settings)
    return AdvisorOrchestrator(service, router, service.llm, rag_settings)
