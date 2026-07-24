"""Tests for `app.agents.router.AdvisorRouter` -- deterministic routing
via retrieval-signal document attribution + keyword substring matching.
No LLM call is ever made by the router itself. Uses a small, isolated
fixture KB and synthetic advisors so signal behavior is fully controlled
and assertable, independent of the real 10-advisor registry/KB.
"""

import pytest

from app.agents.base_agent import Advisor
from app.agents.router import AdvisorRouter
from app.config.settings import IngestionSettings, RouterSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.ingestion.pipeline import IngestionPipeline
from app.rag.retriever import Retriever


def _router_settings(**overrides) -> RouterSettings:
    defaults = dict(
        router_retrieval_top_k=12,
        router_min_confidence=0.15,
        router_supporting_min_ratio=0.4,
        router_max_supporting_advisors=2,
        router_retrieval_weight=0.6,
        router_keyword_weight=0.4,
    )
    defaults.update(overrides)
    return RouterSettings(**defaults)


def _seed_three_document_kb(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "testing.md").write_text(
        "---\ndocument_id: DOC-TESTING\ntitle: Testing Strategy\n---\n\n"
        "# Testing Strategy\n\n## Coverage\n\n"
        + ("Unit and integration test coverage and quality gate evidence are required before every release. " * 15),
        encoding="utf-8",
    )
    (kb_dir / "release.md").write_text(
        "---\ndocument_id: DOC-RELEASE\ntitle: Release Management\n---\n\n"
        "# Release Management\n\n## Canary Rollout\n\n"
        + ("Canary deployment and rollback procedures govern every production release. " * 15),
        encoding="utf-8",
    )
    (kb_dir / "incident.md").write_text(
        "---\ndocument_id: DOC-INCIDENT\ntitle: Incident Management\n---\n\n"
        "# Incident Management\n\n## Severity\n\n"
        + ("A Sev-1 incident requires an incident commander and a war room. " * 15),
        encoding="utf-8",
    )
    return kb_dir


def _build_retriever(tmp_path) -> Retriever:
    kb_dir = _seed_three_document_kb(tmp_path)
    ingestion_settings = IngestionSettings(
        knowledge_base_dirs=(kb_dir,), supported_extensions=(".md",),
        chunk_size=500, chunk_overlap=50, log_level="INFO", output_dir=tmp_path / "processed",
    )
    pipeline = IngestionPipeline(settings=ingestion_settings)

    provider = LocalHashingEmbeddingProvider(dimensions=128)
    store = LocalVectorStore(tmp_path / "store")
    Indexer(provider, store).index_from_pipeline(pipeline)
    return Retriever(provider, store)


_TESTING_ADVISOR = Advisor(
    advisor_id="testing", display_name="Testing Advisor", description="d", persona="p",
    structure_guidance="s", default_filters={"document_id": "DOC-TESTING"},
    domain_keywords=("testing", "test coverage", "quality gate"),
)
_RELEASE_ADVISOR = Advisor(
    advisor_id="release", display_name="Release Advisor", description="d", persona="p",
    structure_guidance="s", default_filters={"document_id": "DOC-RELEASE"},
    domain_keywords=("release", "canary", "rollback", "deployment"),
)
_INCIDENT_ADVISOR = Advisor(
    advisor_id="incident-management", display_name="Incident Management Advisor", description="d", persona="p",
    structure_guidance="s", default_filters={"document_id": "DOC-INCIDENT"},
    domain_keywords=("incident", "sev-1", "severity", "war room", "incident commander"),
)
_ADVISORS = [_TESTING_ADVISOR, _RELEASE_ADVISOR, _INCIDENT_ADVISOR]


def test_obvious_single_domain_question_selects_correct_primary(tmp_path):
    retriever = _build_retriever(tmp_path)
    router = AdvisorRouter(retriever, _ADVISORS, _router_settings())

    decision = router.route("How should a Sev-1 incident with a war room be handled?")

    assert decision.primary_advisor == "incident-management"
    assert decision.fallback_used is False


def test_single_domain_question_selects_no_supporting_advisors(tmp_path):
    retriever = _build_retriever(tmp_path)
    router = AdvisorRouter(retriever, _ADVISORS, _router_settings())

    decision = router.route("How should a Sev-1 incident with a war room be handled?")

    assert decision.supporting_advisors == []


def test_cross_domain_question_selects_a_supporting_advisor(tmp_path):
    retriever = _build_retriever(tmp_path)
    router = AdvisorRouter(retriever, _ADVISORS, _router_settings())

    decision = router.route(
        "What test coverage and quality gate evidence is required before a canary release "
        "and rollback plan is approved for deployment?"
    )

    assert decision.primary_advisor in {"testing", "release"}
    assert len(decision.supporting_advisors) >= 1


def test_supporting_advisors_capped_at_configured_maximum(tmp_path):
    retriever = _build_retriever(tmp_path)
    router = AdvisorRouter(retriever, _ADVISORS, _router_settings(router_max_supporting_advisors=1))

    decision = router.route(
        "What test coverage, canary rollback deployment, and Sev-1 incident commander "
        "war room evidence is required for release?"
    )

    assert len(decision.supporting_advisors) <= 1


def test_unrelated_question_triggers_fallback(tmp_path):
    retriever = _build_retriever(tmp_path)
    router = AdvisorRouter(retriever, _ADVISORS, _router_settings())

    decision = router.route("What is the best recipe for chocolate chip cookies?")

    assert decision.fallback_used is True
    # Still names a valid, resolvable best guess -- no sentinel "none" case.
    assert decision.primary_advisor in {advisor.advisor_id for advisor in _ADVISORS}


def test_detected_domains_reflects_keyword_hits_regardless_of_final_selection(tmp_path):
    retriever = _build_retriever(tmp_path)
    router = AdvisorRouter(retriever, _ADVISORS, _router_settings())

    decision = router.route("Our release canary rollback plan also touches Sev-1 incident response.")

    assert "Release Advisor" in decision.detected_domains
    assert "Incident Management Advisor" in decision.detected_domains


def test_routing_is_deterministic_across_repeated_calls(tmp_path):
    retriever = _build_retriever(tmp_path)
    router = AdvisorRouter(retriever, _ADVISORS, _router_settings())

    first = router.route("How should a Sev-1 incident with a war room be handled?")
    second = router.route("How should a Sev-1 incident with a war room be handled?")

    assert first == second


def test_rationale_cites_both_raw_signal_values(tmp_path):
    retriever = _build_retriever(tmp_path)
    router = AdvisorRouter(retriever, _ADVISORS, _router_settings())

    decision = router.route("How should a Sev-1 incident with a war room be handled?")

    assert "retrieval=" in decision.rationale
    assert "keyword=" in decision.rationale


def test_router_requires_at_least_one_advisor(tmp_path):
    retriever = _build_retriever(tmp_path)
    with pytest.raises(ValueError):
        AdvisorRouter(retriever, [], _router_settings())
