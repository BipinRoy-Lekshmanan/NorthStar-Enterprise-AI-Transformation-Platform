"""Grounded question-answering application service (Milestone 7).

Thin facade over `RagService.ask()` (manual advisor selection) and
`AdvisorOrchestrator.ask()` (automatic routing) -- no retrieval, prompt,
or model-provider logic lives here. Routes call exactly one function
below and translate nothing themselves; domain exceptions
(`QuestionValidationError`, `ModelProviderError`, `UnknownAdvisorError`)
bubble through unmodified to the handlers registered in `app.api.errors`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.agents.orchestrator import AdvisorOrchestrator
from app.agents.registry import get_advisor, list_advisors
from app.agents.router import AdvisorRouter
from app.audit.logger import AuditContext, record_from_context
from app.config.settings import RagSettings, RouterSettings
from app.models.citation import Citation
from app.models.query import RetrievalQuery
from app.models.response import RagAnswer
from app.models.workflow import WorkflowStageResult
from app.rag.pipeline import RagService
from app.services.llm_service import ModelProviderError
from app.telemetry.metrics import (
    advisor_duration_seconds,
    advisor_executions_total,
    rag_citations_count,
    rag_model_duration_seconds,
    rag_questions_total,
    rag_retrieval_duration_seconds,
    rag_total_duration_seconds,
    routing_confidence,
    routing_decisions_total,
)
from app.telemetry.tracing import traced_span
from app.workflows.conflict_detection import detect_conflicts


@dataclass(frozen=True)
class QueryFilters:
    document_id: str | None = None
    source_file: str | None = None

    def as_dict(self) -> dict[str, str]:
        result: dict[str, str] = {}
        if self.document_id:
            result["document_id"] = self.document_id
        if self.source_file:
            result["source_file"] = self.source_file
        return result


@dataclass(frozen=True)
class RetrievedChunk:
    source_id: str
    text: str
    score: float


@dataclass(frozen=True)
class QueryResult:
    question: str
    answer: str
    sufficient_context: bool
    primary_advisor: str | None
    supporting_advisors: list[str] = field(default_factory=list)
    confidence: float | None = None
    routing_rationale: str | None = None
    fallback_used: bool | None = None
    citations: list[Citation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    diagnostics: dict | None = None
    retrieved_context: list[RetrievedChunk] | None = None
    degraded: bool = False


def _diagnostics_dict(answer: RagAnswer) -> dict:
    return answer.diagnostics.model_dump(mode="json")


def _record_rag_metrics(answer: RagAnswer, *, mode: str, advisor_id: str) -> None:
    diagnostics = answer.diagnostics
    rag_questions_total.labels(
        advisor=advisor_id, mode=mode, sufficient_context=str(answer.sufficient_context).lower(),
    ).inc()
    rag_retrieval_duration_seconds.observe(diagnostics.retrieval_duration_ms / 1000)
    rag_total_duration_seconds.observe(diagnostics.total_duration_ms / 1000)
    rag_citations_count.observe(len(answer.citations))
    if diagnostics.model_latency_ms is not None:
        rag_model_duration_seconds.labels(provider=diagnostics.model_provider or "unknown").observe(
            diagnostics.model_latency_ms / 1000
        )


_DEGRADED_ANSWER_NOTICE = (
    "A generated answer is currently unavailable because the language model provider could not be "
    "reached. The most relevant excerpts from the Northstar knowledge base are shown below -- review "
    "them directly rather than relying on a generated summary."
)


def _degraded_query_result(
    service: RagService, question: str, advisor_id: str | None, filters: QueryFilters, exc: Exception,
) -> QueryResult:
    """Graceful degradation when the model provider is unavailable
    (`ModelProviderError` and subclasses, including a translated
    `CircuitBreakerOpenError`): semantic retrieval still runs -- it has
    its own, independent failure mode and provider -- so real, grounded
    excerpts are still useful even with no generated answer. Never
    fabricates a citation or an answer from general model knowledge;
    `citations` stays empty because nothing was actually cited, and
    `retrieved_context` is always populated here regardless of the
    caller's `include_context` flag, since surfacing raw excerpts is
    the entire point of this path."""
    response = service.retriever.retrieve(RetrievalQuery(text=question, top_k=10, filters=filters.as_dict()))
    retrieved_context = [
        RetrievedChunk(source_id=f"S{i}", text=result.chunk.text, score=result.score)
        for i, result in enumerate(response.results, start=1)
    ]
    return QueryResult(
        question=question,
        answer=_DEGRADED_ANSWER_NOTICE,
        sufficient_context=False,
        primary_advisor=advisor_id,
        warnings=[f"Model provider unavailable: {exc}"],
        retrieved_context=retrieved_context,
        degraded=True,
    )


def ask_manual(
    service: RagService,
    question: str,
    advisor_id: str,
    filters: QueryFilters,
    include_diagnostics: bool = False,
    include_context: bool = False,
    audit: AuditContext | None = None,
) -> QueryResult:
    """Ask a specific advisor by id. Raises `UnknownAdvisorError` (mapped
    to 404 by `app.api.errors`) for an unrecognized `advisor_id`."""
    advisor = get_advisor(advisor_id)

    captured_context: list[RetrievedChunk] = []

    def _capture(context_result):
        for block in context_result.blocks:
            captured_context.append(
                RetrievedChunk(source_id=block.source_id, text=block.chunk.text, score=block.score)
            )

    try:
        with (
            traced_span("advisor.ask", advisor_id=advisor_id, mode="manual"),
            advisor_duration_seconds.labels(advisor_id=advisor_id).time(),
        ):
            answer = advisor.ask(
                service, question, filters=filters.as_dict(),
                on_context_built=_capture if include_context else None,
            )
    except ModelProviderError as exc:
        result = _degraded_query_result(service, question, advisor_id, filters, exc)
        record_from_context(
            audit, action="grounded_question_asked", resource_type="advisor", resource_id=advisor_id,
            metadata={"degraded": True, "sufficient_context": False},
        )
        return result

    advisor_executions_total.labels(advisor_id=advisor_id).inc()
    _record_rag_metrics(answer, mode="manual", advisor_id=advisor_id)

    record_from_context(
        audit, action="grounded_question_asked", resource_type="advisor", resource_id=advisor_id,
        metadata={"sufficient_context": answer.sufficient_context, "citation_count": len(answer.citations)},
    )

    return QueryResult(
        question=question,
        answer=answer.answer,
        sufficient_context=answer.sufficient_context,
        primary_advisor=advisor_id,
        citations=answer.citations,
        warnings=answer.warnings,
        diagnostics=_diagnostics_dict(answer) if include_diagnostics else None,
        retrieved_context=captured_context if include_context else None,
    )


def ask_auto(
    service: RagService,
    rag_settings: RagSettings,
    router_settings: RouterSettings,
    question: str,
    filters: QueryFilters,
    max_supporting_advisors: int | None = None,
    include_diagnostics: bool = False,
    include_context: bool = False,
    audit: AuditContext | None = None,
) -> QueryResult:
    """Ask via deterministic automatic advisor routing + bounded
    multi-advisor synthesis (Milestone 5).

    `filters` and `include_context` are only meaningful for manual
    advisor selection -- `AdvisorOrchestrator.ask()` takes just a
    question, with no filter or context-capture hook, so both become a
    visible warning here rather than being silently dropped.
    """
    warnings: list[str] = []
    if filters.as_dict():
        warnings.append("Filters are only applied to manual advisor selection; ignored for automatic routing.")
    if include_context:
        warnings.append("Retrieved-context capture is only available for manual advisor selection.")

    settings = router_settings
    if max_supporting_advisors is not None:
        settings = dataclasses.replace(router_settings, router_max_supporting_advisors=max_supporting_advisors)

    router = AdvisorRouter(service.retriever, list_advisors(), settings)
    orchestrator = AdvisorOrchestrator(service, router, service.llm, rag_settings)

    try:
        with traced_span("advisor.ask", mode="auto"):
            response = orchestrator.ask(question)
    except ModelProviderError as exc:
        result = _degraded_query_result(service, question, None, QueryFilters(), exc)
        record_from_context(
            audit, action="grounded_question_asked", resource_type="advisor", resource_id=None,
            metadata={"mode": "auto", "degraded": True, "sufficient_context": False},
        )
        return result
    warnings.extend(response.warnings)

    routing_decisions_total.labels(
        primary_advisor=response.routing.primary_advisor,
        fallback_used=str(response.routing.fallback_used).lower(),
    ).inc()
    routing_confidence.observe(response.routing.confidence)
    _record_rag_metrics(response.primary_answer, mode="auto", advisor_id=response.routing.primary_advisor)

    conflicts = _detect_conflicts_for_response(response) if response.supporting_answers else []

    record_from_context(
        audit, action="grounded_question_asked", resource_type="advisor", resource_id=response.routing.primary_advisor,
        metadata={
            "mode": "auto",
            "sufficient_context": response.primary_answer.sufficient_context,
            "supporting_advisors": response.routing.supporting_advisors,
            "fallback_used": response.routing.fallback_used,
        },
    )

    return QueryResult(
        question=question,
        answer=response.answer,
        sufficient_context=response.primary_answer.sufficient_context,
        primary_advisor=response.routing.primary_advisor,
        supporting_advisors=response.routing.supporting_advisors,
        confidence=response.routing.confidence,
        routing_rationale=response.routing.rationale,
        fallback_used=response.routing.fallback_used,
        citations=response.citations,
        warnings=warnings,
        conflicts=conflicts,
        diagnostics=_diagnostics_dict(response.primary_answer) if include_diagnostics else None,
    )


def _detect_conflicts_for_response(response) -> list[str]:
    """Reuses Milestone 6's rule-based conflict detection for a
    multi-advisor query response -- `detect_conflicts()` only needs
    `WorkflowStageResult`-shaped objects (advisor_name, answer, status),
    which the orchestrator's primary/supporting `RagAnswer`s map onto
    directly. No workflow, no persistence, no new detection logic."""
    now = datetime.now(timezone.utc)
    stage_results = [
        WorkflowStageResult(
            stage_id=response.routing.primary_advisor, stage_name=response.routing.primary_advisor,
            status="completed", started_at=now, advisor_name=response.routing.primary_advisor,
            answer=response.primary_answer.answer,
        ),
    ]
    for advisor_id, answer in zip(response.routing.supporting_advisors, response.supporting_answers):
        stage_results.append(
            WorkflowStageResult(
                stage_id=advisor_id, stage_name=advisor_id, status="completed", started_at=now,
                advisor_name=advisor_id, answer=answer.answer,
            )
        )

    findings = detect_conflicts(stage_results)
    return [f"{finding.title}: {finding.description}" for finding in findings]
