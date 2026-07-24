"""Tests for `ReviewFinding` (`app.models.workflow`) -- creation,
severity/status normalization, blocking semantics, citation preservation,
and conflict-detection's natural dedup (one finding per topic, not one
per matched phrase).
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.citation import Citation
from app.models.workflow import ReviewFinding, WorkflowStageResult
from app.workflows.conflict_detection import detect_conflicts

_NOW = datetime.now(timezone.utc)


def _citation(chunk_id):
    return Citation(
        source_id="S1", chunk_id=chunk_id, document_title="Doc", source_file="f.md",
        source_path="p/f.md", section_title="Sec", score=0.5, excerpt="...",
    )


def test_finding_creation_with_required_fields():
    finding = ReviewFinding(
        finding_id="f1", category="security", title="Missing MFA", description="No MFA enforced.",
        severity="high",
    )
    assert finding.finding_id == "f1"
    assert finding.blocking is False  # default
    assert finding.status == "open"  # default


def test_invalid_severity_is_rejected():
    with pytest.raises(ValidationError, match="severity"):
        ReviewFinding(finding_id="f1", category="c", title="t", description="d", severity="super-bad")


def test_invalid_status_is_rejected():
    with pytest.raises(ValidationError, match="status"):
        ReviewFinding(finding_id="f1", category="c", title="t", description="d", severity="low", status="bogus")


@pytest.mark.parametrize("severity", ["critical", "high", "medium", "low", "informational"])
def test_all_valid_severities_are_accepted(severity):
    finding = ReviewFinding(finding_id="f1", category="c", title="t", description="d", severity=severity)
    assert finding.severity == severity


@pytest.mark.parametrize("status", ["open", "accepted", "mitigated", "deferred", "not_applicable"])
def test_all_valid_statuses_are_accepted(status):
    finding = ReviewFinding(finding_id="f1", category="c", title="t", description="d", severity="low", status=status)
    assert finding.status == status


def test_blocking_finding_is_explicit_not_inferred_from_severity():
    # A "critical" severity finding is not automatically blocking -- blocking
    # is its own explicit field, set by whoever creates the finding.
    finding = ReviewFinding(finding_id="f1", category="c", title="t", description="d", severity="critical")
    assert finding.blocking is False


def test_citations_are_preserved_through_round_trip():
    finding = ReviewFinding(
        finding_id="f1", category="c", title="t", description="d", severity="low",
        citations=[_citation("c1"), _citation("c2")],
    )
    dumped = finding.model_dump(mode="json")
    reloaded = ReviewFinding.model_validate(dumped)
    assert [c.chunk_id for c in reloaded.citations] == ["c1", "c2"]


def test_conflict_detection_produces_one_finding_per_topic_not_per_phrase_occurrence():
    # The topic "rollback" is mentioned multiple times by each advisor with a
    # consistent stance -- should still collapse to exactly one finding.
    results = [
        WorkflowStageResult(
            stage_id="release", stage_name="Release", status="completed", started_at=_NOW,
            advisor_name="release",
            answer="Rollback plan is adequate. The rollback plan is also sufficient for this change.",
        ),
        WorkflowStageResult(
            stage_id="security", stage_name="Security", status="completed", started_at=_NOW,
            advisor_name="security",
            answer="No rollback procedure documented -- a blocking risk. This rollback gap is a blocking risk.",
        ),
    ]
    findings = detect_conflicts(results)
    assert len(findings) == 1
