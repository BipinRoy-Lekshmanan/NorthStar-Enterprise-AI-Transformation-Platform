"""Tests for `app.workflows.conflict_detection` -- rule-based,
literal-string conflict detection between advisor stage results.
"""

from datetime import datetime, timezone

from app.models.workflow import WorkflowStageResult
from app.workflows.conflict_detection import detect_conflicts

_NOW = datetime.now(timezone.utc)


def _result(advisor_name, answer, status="completed"):
    return WorkflowStageResult(
        stage_id=advisor_name, stage_name=advisor_name, status=status, started_at=_NOW,
        advisor_name=advisor_name, answer=answer,
    )


def test_positive_vs_blocking_stance_on_same_topic_is_a_conflict():
    results = [
        _result("release", "Release readiness is sufficient; rollback plan is in place and adequate."),
        _result("security", "Security review found a critical gap: no rollback procedure documented, a blocking risk."),
    ]
    findings = detect_conflicts(results)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.category == "conflict"
    assert finding.blocking is True
    assert finding.severity == "high"
    assert set(finding.source_advisors) == {"release", "security"}


def test_agreement_on_same_topic_produces_no_conflict():
    results = [
        _result("testing", "Test coverage meets requirements and is acceptable for release."),
        _result("release", "Release readiness looks fine, no concerns."),
    ]
    assert detect_conflicts(results) == []


def test_unrelated_topics_produce_no_conflict():
    results = [
        _result("testing", "Test coverage meets requirements."),
        _result("security", "Security review found a critical gap in access control, a blocking risk."),
    ]
    assert detect_conflicts(results) == []


def test_non_advisor_stage_results_are_ignored():
    results = [
        WorkflowStageResult(stage_id="validate", stage_name="Validate", status="completed", started_at=_NOW),
        _result("release", "Release readiness is sufficient; rollback plan is in place."),
    ]
    assert detect_conflicts(results) == []


def test_incomplete_advisor_stage_results_are_ignored():
    results = [
        _result("release", "Release readiness is sufficient; rollback plan is in place and adequate.", status="failed"),
        _result("security", "Security review found a critical gap: no rollback procedure documented, a blocking risk."),
    ]
    assert detect_conflicts(results) == []


def test_conflict_finding_quotes_the_matched_phrases():
    results = [
        _result("release", "Rollback plan is in place and adequate."),
        _result("security", "There is no rollback procedure documented, a critical gap."),
    ]
    findings = detect_conflicts(results)
    assert len(findings) == 1
    assert "matched phrase" in findings[0].description
    assert "release" in findings[0].description
    assert "security" in findings[0].description


def test_multiple_topics_can_each_produce_a_conflict():
    results = [
        _result("release", "Rollback plan is adequate. Monitoring is in place and acceptable."),
        _result("security", "No rollback procedure documented -- a blocking risk. Also, monitoring is insufficient."),
    ]
    findings = detect_conflicts(results)
    topics = {f.title for f in findings}
    assert len(findings) == 2
    assert any("rollback" in t.lower() for t in topics)
    assert any("monitoring" in t.lower() for t in topics)
