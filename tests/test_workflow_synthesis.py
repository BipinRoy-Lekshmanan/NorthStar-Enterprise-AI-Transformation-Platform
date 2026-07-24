"""Tests for `app.workflows.synthesis` -- the workflow's one bounded
synthesis call and citation dedup, plus provider-failure fallback.
"""

from datetime import datetime, timezone

from app.config.prompt_config import WorkflowSynthesisInput, build_workflow_synthesis_prompt
from app.models.citation import Citation
from app.models.workflow import EvidenceGap, ReviewFinding, WorkflowStageResult
from app.services.llm_service import FakeModelProvider, ModelProviderError, ModelUnavailableError
from app.workflows.synthesis import dedupe_citations, run_synthesis_stage

_NOW = datetime.now(timezone.utc)


def _citation(chunk_id, source_id="S1"):
    return Citation(
        source_id=source_id, chunk_id=chunk_id, document_title="Doc", source_file="f.md",
        source_path="p/f.md", section_title="Sec", score=0.5, excerpt="...",
    )


class _FailingProvider:
    def generate(self, **kwargs):
        raise ModelUnavailableError("simulated provider outage")


def test_build_workflow_synthesis_prompt_includes_all_supplied_sections():
    data = WorkflowSynthesisInput(
        workflow_name="Production Readiness Review",
        report_sections=("Executive Summary", "Recommendation"),
        stage_findings_text="[Release Review -- release]\nLooks ready.",
        review_findings_text="- [HIGH] Conflict on rollback",
        evidence_gaps_text="- [CRITICAL (BLOCKING)] rollback_plan: missing",
        conflicts_text="- [HIGH] Conflict on rollback",
        approval_comments_text="Proceed with conditions.",
    )
    prompt = build_workflow_synthesis_prompt("Assess readiness.", data)

    assert "Production Readiness Review" in prompt.user
    assert "Executive Summary" in prompt.system
    assert "Recommendation" in prompt.system
    assert "Looks ready." in prompt.user
    assert "rollback_plan: missing" in prompt.user
    assert "Proceed with conditions." in prompt.user
    assert "workflow-v1" in prompt.version


def test_build_workflow_synthesis_prompt_omits_absent_optional_sections():
    data = WorkflowSynthesisInput(
        workflow_name="W", report_sections=("Summary",), stage_findings_text="findings",
        review_findings_text="", evidence_gaps_text="", conflicts_text="", approval_comments_text=None,
    )
    prompt = build_workflow_synthesis_prompt("Q?", data)
    assert "Human approval comments:" not in prompt.user
    assert "Detected conflicts:" not in prompt.user


def test_run_synthesis_stage_completes_with_fake_provider():
    stage_results = [
        WorkflowStageResult(
            stage_id="release_review", stage_name="Release Review", status="completed", started_at=_NOW,
            advisor_name="release", answer="Looks ready.", citations=[_citation("c1")],
        ),
    ]
    result = run_synthesis_stage(
        FakeModelProvider(), stage_id="synthesis", stage_name="Executive Synthesis",
        workflow_name="Production Readiness Review", question="Assess readiness.",
        report_sections=("Executive Summary",), stage_results=stage_results,
        review_findings=[], evidence_gaps=[], conflicts=[], approval_comments=None,
        temperature=0.0, max_tokens=1024,
    )
    assert result.status == "completed"
    assert result.answer
    assert result.citations == [_citation("c1")]
    assert result.diagnostics["provider"] == "fake"


def test_run_synthesis_stage_provider_failure_produces_failed_result_not_a_crash():
    result = run_synthesis_stage(
        _FailingProvider(), stage_id="synthesis", stage_name="Executive Synthesis",
        workflow_name="W", question="Q?", report_sections=("Summary",),
        stage_results=[], review_findings=[], evidence_gaps=[], conflicts=[], approval_comments=None,
        temperature=0.0, max_tokens=1024,
    )
    assert result.status == "failed"
    assert result.answer is None
    assert result.errors and "Synthesis failed" in result.errors[0]


def test_dedupe_citations_is_order_preserving_and_deduped_by_chunk_id():
    results = [
        WorkflowStageResult(
            stage_id="a", stage_name="A", status="completed", started_at=_NOW,
            advisor_name="a", citations=[_citation("c1"), _citation("c2")],
        ),
        WorkflowStageResult(
            stage_id="b", stage_name="B", status="completed", started_at=_NOW,
            advisor_name="b", citations=[_citation("c2"), _citation("c3")],
        ),
    ]
    citations = dedupe_citations(results)
    assert [c.chunk_id for c in citations] == ["c1", "c2", "c3"]
