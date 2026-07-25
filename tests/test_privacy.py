"""Tests for `app.config.privacy` (Milestone 8) -- `PrivacySettings` and
`redact_citation_excerpts`.
"""

from app.config.privacy import REDACTED_EXCERPT, PrivacySettings, redact_citation_excerpts
from app.models.citation import Citation


def _citation(excerpt="sensitive source text") -> Citation:
    return Citation(
        source_id="S1", chunk_id="c1", source_file="f.md", source_path="f.md", score=0.9, excerpt=excerpt,
    )


def test_privacy_settings_defaults_to_including_excerpts():
    settings = PrivacySettings.from_env(env={})
    assert settings.include_citation_excerpts is True


def test_privacy_settings_can_disable_excerpts():
    settings = PrivacySettings.from_env(env={"INCLUDE_CITATION_EXCERPTS": "false"})
    assert settings.include_citation_excerpts is False


def test_redact_is_a_no_op_when_excerpts_are_included():
    citations = [_citation()]
    result = redact_citation_excerpts(citations, include_excerpts=True)
    assert result is citations
    assert result[0].excerpt == "sensitive source text"


def test_redact_replaces_excerpt_text_when_disabled():
    citation = _citation()
    result = redact_citation_excerpts([citation], include_excerpts=False)
    assert result[0].excerpt == REDACTED_EXCERPT
    assert result[0].excerpt != citation.excerpt


def test_redact_preserves_every_other_field():
    citation = _citation()
    result = redact_citation_excerpts([citation], include_excerpts=False)[0]
    assert result.source_id == citation.source_id
    assert result.document_id == citation.document_id
    assert result.source_file == citation.source_file
    assert result.score == citation.score


def test_redact_handles_an_empty_list():
    assert redact_citation_excerpts([], include_excerpts=False) == []
