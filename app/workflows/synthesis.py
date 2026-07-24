"""Workflow "Executive Synthesis" stage body (Milestone 6).

Renders already-completed stage results, structured findings, evidence
gaps, and any human approval comments into plain text blocks and makes
exactly one bounded LLM call via `build_workflow_synthesis_prompt()` --
the same "at most one extra call" shape `AdvisorOrchestrator` uses for
advisor-level synthesis (Milestone 5). Never touches the vector store or
calls a vendor SDK directly; the `LanguageModelProvider` is passed in by
the caller (`app.workflows.engine.WorkflowEngine`), exactly like
`RagService`/`AdvisorOrchestrator` already do.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from app.config.prompt_config import WorkflowSynthesisInput, build_workflow_synthesis_prompt
from app.models.citation import Citation
from app.models.workflow import EvidenceGap, ReviewFinding, WorkflowStageResult
from app.services.llm_service import LanguageModelProvider, ModelProviderError


def _render_stage_findings(stage_results: list[WorkflowStageResult]) -> str:
    lines = [
        f"[{result.stage_name} -- {result.advisor_name}]\n{result.answer.strip()}"
        for result in stage_results
        if result.advisor_name and result.answer
    ]
    return "\n\n".join(lines)


def _render_findings(findings: list[ReviewFinding]) -> str:
    lines = []
    for finding in findings:
        blocking_tag = " (BLOCKING)" if finding.blocking else ""
        lines.append(f"- [{finding.severity.upper()}{blocking_tag}] {finding.title}: {finding.description}")
    return "\n".join(lines)


def _render_evidence_gaps(gaps: list[EvidenceGap]) -> str:
    lines = []
    for gap in gaps:
        blocking_tag = " (BLOCKING)" if gap.blocking else ""
        lines.append(f"- [{gap.severity.upper()}{blocking_tag}] {gap.field}: {gap.description}")
    return "\n".join(lines)


def dedupe_citations(stage_results: list[WorkflowStageResult]) -> list[Citation]:
    """Union of every stage result's citations, deduped by `chunk_id`,
    order-preserving. Never re-derived from synthesis text -- nothing the
    synthesis stage writes can fabricate a citation. Reused by
    `app.workflows.report` for the report's Sources section."""
    seen: set[str] = set()
    result: list[Citation] = []
    for stage_result in stage_results:
        for citation in stage_result.citations:
            if citation.chunk_id in seen:
                continue
            seen.add(citation.chunk_id)
            result.append(citation)
    return result


def run_synthesis_stage(
    llm: LanguageModelProvider,
    *,
    stage_id: str,
    stage_name: str,
    workflow_name: str,
    question: str,
    report_sections: tuple[str, ...],
    stage_results: list[WorkflowStageResult],
    review_findings: list[ReviewFinding],
    evidence_gaps: list[EvidenceGap],
    conflicts: list[ReviewFinding],
    approval_comments: str | None,
    temperature: float,
    max_tokens: int | None,
) -> WorkflowStageResult:
    """Run the workflow's one bounded synthesis call and return its
    `WorkflowStageResult`. A `ModelProviderError` produces a `"failed"`
    stage result rather than propagating -- the engine's required/optional
    stage logic then decides whether that halts the workflow."""
    started_at = datetime.now(timezone.utc)
    start = time.perf_counter()

    data = WorkflowSynthesisInput(
        workflow_name=workflow_name,
        report_sections=report_sections,
        stage_findings_text=_render_stage_findings(stage_results),
        review_findings_text=_render_findings(review_findings),
        evidence_gaps_text=_render_evidence_gaps(evidence_gaps),
        conflicts_text=_render_findings(conflicts),
        approval_comments_text=approval_comments,
    )
    prompt = build_workflow_synthesis_prompt(question, data)
    citations = dedupe_citations(stage_results)

    try:
        model_response = llm.generate(
            system_prompt=prompt.system,
            user_prompt=prompt.user,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except ModelProviderError as exc:
        return WorkflowStageResult(
            stage_id=stage_id,
            stage_name=stage_name,
            status="failed",
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            answer=None,
            citations=citations,
            errors=[f"Synthesis failed: {exc}"],
            diagnostics={"duration_ms": (time.perf_counter() - start) * 1000},
        )

    return WorkflowStageResult(
        stage_id=stage_id,
        stage_name=stage_name,
        status="completed",
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        answer=model_response.text,
        citations=citations,
        diagnostics={
            "provider": model_response.provider,
            "model": model_response.model,
            "latency_ms": model_response.latency_ms,
            "duration_ms": (time.perf_counter() - start) * 1000,
        },
    )
