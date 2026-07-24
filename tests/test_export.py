"""Tests for `app.export` (Milestone 7): envelope building, Markdown
rendering, and JSON rendering for both query answers and workflow
reports. Pure formatting over hand-crafted dicts -- no API/engine
dependency needed.
"""

import json

from app.export.common import build_query_export_envelope, build_workflow_report_export_envelope
from app.export.json_renderer import render_export_json
from app.export.markdown_renderer import render_query_answer_markdown, render_workflow_report_markdown

_QUERY_RESPONSE = {
    "question": "What testing evidence is required before release?",
    "answer": "Full regression coverage is required. [S1]",
    "sufficient_context": True,
    "routing": {
        "primary_advisor": "testing", "supporting_advisors": ["release-management"],
        "confidence": 0.82, "rationale": "keyword match", "fallback_used": False, "mode": "auto",
    },
    "citations": [
        {"source_id": "S1", "document_title": "Testing Strategy", "source_file": "14_Testing_Strategy.md",
         "section_title": "Coverage", "excerpt": "..."},
    ],
    "warnings": ["Low confidence routing"],
    "conflicts": ["Advisor A and Advisor B disagree on rollback timing"],
}

_WORKFLOW_EXECUTION = {
    "execution_id": "exec-1", "workflow_id": "production_readiness_review", "status": "completed",
    "findings": [{"title": "Missing rollback plan", "description": "No rollback documented.",
                  "severity": "critical", "blocking": True}],
    "evidence_gaps": [{"field": "rollback_plan", "description": "No rollback plan provided.",
                        "severity": "critical", "blocking": True}],
    "conflicts": [{"title": "Security vs Release", "source_advisors": ["security", "release-management"],
                    "description": "Disagreement on deployment window."}],
    "citations": [
        {"source_id": "S1", "document_title": "Release Management", "source_file": "15_Release_Management.md",
         "section_title": "Rollback"},
    ],
}

_WORKFLOW_REPORT = {"sections": {"Summary": "Overall risk is elevated.", "Recommendation": "NO_GO"}}


def test_build_query_export_envelope_includes_disclaimer():
    envelope = build_query_export_envelope(_QUERY_RESPONSE)
    assert envelope["question"] == _QUERY_RESPONSE["question"]
    assert envelope["disclaimer"]
    assert envelope["generated_at"]


def test_build_workflow_report_export_envelope_merges_report_and_execution():
    envelope = build_workflow_report_export_envelope(_WORKFLOW_REPORT, _WORKFLOW_EXECUTION)
    assert envelope["execution_id"] == "exec-1"
    assert envelope["sections"] == _WORKFLOW_REPORT["sections"]
    assert envelope["findings"] == _WORKFLOW_EXECUTION["findings"]


def test_query_markdown_includes_question_answer_citations_and_disclaimer():
    envelope = build_query_export_envelope(_QUERY_RESPONSE)
    markdown = render_query_answer_markdown(envelope)
    assert "# Grounded Query Answer" in markdown
    assert _QUERY_RESPONSE["question"] in markdown
    assert "Testing Strategy" in markdown
    assert "Low confidence routing" in markdown
    assert envelope["disclaimer"] in markdown


def test_query_markdown_flags_insufficient_context():
    envelope = build_query_export_envelope({**_QUERY_RESPONSE, "sufficient_context": False})
    markdown = render_query_answer_markdown(envelope)
    assert "did not contain sufficient context" in markdown


def test_workflow_report_markdown_includes_sections_findings_and_citations():
    envelope = build_workflow_report_export_envelope(_WORKFLOW_REPORT, _WORKFLOW_EXECUTION)
    markdown = render_workflow_report_markdown(envelope)
    assert "## Summary" in markdown
    assert "Overall risk is elevated." in markdown
    assert "Missing rollback plan" in markdown
    assert "Release Management" in markdown
    assert envelope["disclaimer"] in markdown


def test_json_renderer_round_trips_the_envelope():
    envelope = build_query_export_envelope(_QUERY_RESPONSE)
    rendered = render_export_json(envelope)
    assert json.loads(rendered) == envelope


def test_json_renderer_never_leaks_a_python_repr_for_nested_dicts():
    envelope = build_workflow_report_export_envelope(_WORKFLOW_REPORT, _WORKFLOW_EXECUTION)
    rendered = render_export_json(envelope)
    parsed = json.loads(rendered)
    assert parsed["findings"][0]["title"] == "Missing rollback plan"
