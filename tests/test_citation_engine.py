from app.models.chunk import Chunk
from app.rag.citation_engine import build_citations, parse_citation_ids
from app.rag.context_builder import ContextBlock


def _block(source_id: str, **overrides) -> ContextBlock:
    fields = dict(
        chunk_id=f"chunk-{source_id}",
        text="Some retrieved content about incidents.",
        chunk_index=0,
        document_title="Incident Management Standard",
        document_id="NLC-ENG-007",
        source_file="16_Incident_Management.md",
        source_path="04_Engineering/16_Incident_Management.md",
        section_title="Major Incident Management",
        heading_path=["Major Incident Management"],
        content_hash="hash",
        char_count=40,
    )
    fields.update(overrides)
    return ContextBlock(source_id=source_id, chunk=Chunk(**fields), score=0.55)


def test_parse_valid_citations_in_order():
    text = "Answer text [S2] more text [S1] end."
    ids, warnings = parse_citation_ids(text, valid_ids={"S1", "S2"})

    assert ids == ["S2", "S1"]
    assert warnings == []


def test_parse_deduplicates_repeated_citations_preserving_first_use():
    text = "[S1] some claim, [S2] another, [S1] again."
    ids, warnings = parse_citation_ids(text, valid_ids={"S1", "S2"})

    assert ids == ["S1", "S2"]


def test_parse_rejects_unknown_citation_ids():
    text = "Claim backed by [S1] and also [S9]."
    ids, warnings = parse_citation_ids(text, valid_ids={"S1"})

    assert ids == ["S1"]
    assert any("S9" in w for w in warnings)


def test_parse_no_citations_produces_warning():
    ids, warnings = parse_citation_ids("An answer with no citations at all.", valid_ids={"S1"})

    assert ids == []
    assert any("did not cite" in w.lower() for w in warnings)


def test_build_citations_only_for_cited_ids():
    blocks = [_block("S1"), _block("S2"), _block("S3")]

    citations = build_citations(["S1", "S3"], blocks)

    assert [c.source_id for c in citations] == ["S1", "S3"]


def test_build_citations_preserves_metadata_from_chunk():
    blocks = [_block("S1")]

    citations = build_citations(["S1"], blocks)

    citation = citations[0]
    assert citation.document_title == "Incident Management Standard"
    assert citation.document_id == "NLC-ENG-007"
    assert citation.source_file == "16_Incident_Management.md"
    assert citation.source_path == "04_Engineering/16_Incident_Management.md"
    assert citation.section_title == "Major Incident Management"
    assert citation.heading_path == ["Major Incident Management"]
    assert citation.score == 0.55


def test_build_citations_skips_unknown_ids_silently():
    blocks = [_block("S1")]

    citations = build_citations(["S1", "S9"], blocks)

    assert [c.source_id for c in citations] == ["S1"]


def test_build_citations_truncates_long_excerpts():
    blocks = [_block("S1", text="x" * 500, char_count=500)]

    citations = build_citations(["S1"], blocks, excerpt_length=50)

    assert len(citations[0].excerpt) <= 53  # 50 chars + "..."
    assert citations[0].excerpt.endswith("...")


def test_build_citations_no_truncation_when_short():
    blocks = [_block("S1", text="short text", char_count=10)]

    citations = build_citations(["S1"], blocks, excerpt_length=240)

    assert citations[0].excerpt == "short text"
