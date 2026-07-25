"""Tests for `app.telemetry.metrics` (Milestone 8) -- collectors exist,
labeled correctly, and render as valid Prometheus text exposition
format. Uses a private `CollectorRegistry` (not the process-wide
default), so these tests never interfere with -- or are polluted by --
any other test that imports `app.telemetry.metrics`.
"""

from __future__ import annotations

from prometheus_client import parser

from app.telemetry.metrics import render_latest


def test_render_latest_returns_valid_prometheus_text():
    body, content_type = render_latest()
    assert "text/plain" in content_type
    families = list(parser.text_string_to_metric_families(body.decode("utf-8")))
    # The parser normalizes Counter family names by stripping the "_total"
    # convention suffix (e.g. "api_requests_total" -> "api_requests") --
    # this is the parser's own behavior, not this module's naming.
    names = {family.name for family in families}
    assert "api_requests" in names
    assert "rag_questions" in names
    assert "workflows_started" in names
    assert "knowledge_chunks_indexed" in names
    assert "evaluation_runs" in names


def test_no_high_cardinality_label_named_question_or_document():
    """Regression guard: no metric should carry a raw question, document
    id, or citation text as a label -- only bounded/enumerable values."""
    body, _ = render_latest()
    families = list(parser.text_string_to_metric_families(body.decode("utf-8")))
    for family in families:
        for sample in family.samples:
            assert "question" not in sample.labels
            assert "document_id" not in sample.labels
            assert "execution_id" not in sample.labels
