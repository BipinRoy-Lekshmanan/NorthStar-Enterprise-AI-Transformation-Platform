from app.ingestion.metadata_extractor import extract_headings, extract_metadata, split_frontmatter


def test_split_frontmatter_extracts_yaml_block():
    content = "---\ndocument_id: NLC-X-001\ntitle: Sample\n---\n\n# Sample\n\nBody.\n"

    frontmatter, body = split_frontmatter(content)

    assert frontmatter == {"document_id": "NLC-X-001", "title": "Sample"}
    assert body.strip().startswith("# Sample")


def test_split_frontmatter_absent_returns_empty_and_full_content():
    content = "# No Frontmatter\n\nJust a body.\n"

    frontmatter, body = split_frontmatter(content)

    assert frontmatter == {}
    assert body == content


def test_split_frontmatter_malformed_yaml_falls_back_gracefully():
    content = "---\ntitle: [unclosed\n---\n\n# Heading\n"

    frontmatter, body = split_frontmatter(content)

    assert frontmatter == {}
    assert body == content


def test_extract_headings_returns_levels_and_text_in_order():
    body = "# Top\n\nintro\n\n## Sub One\n\ntext\n\n## Sub Two\n\nmore text\n"

    headings = extract_headings(body)

    assert [(h.level, h.text) for h in headings] == [(1, "Top"), (2, "Sub One"), (2, "Sub Two")]


def test_extract_metadata_reads_known_frontmatter_fields():
    content = (
        "---\n"
        "document_id: NLC-ENG-999\n"
        "title: Sample Standard\n"
        "owner: VP, Engineering\n"
        "version: 1.0\n"
        "status: Approved\n"
        "classification: Internal\n"
        "review_cycle: Annual\n"
        "related_documents:\n"
        "  - 01_Other.md\n"
        "  - 02_Other.md\n"
        "---\n\n# Sample Standard\n\nBody.\n"
    )

    metadata = extract_metadata(content, "sample.md")

    assert metadata.document_id == "NLC-ENG-999"
    assert metadata.title == "Sample Standard"
    assert metadata.owner == "VP, Engineering"
    assert metadata.version == "1.0"
    assert metadata.status == "Approved"
    assert metadata.classification == "Internal"
    assert metadata.review_cycle == "Annual"
    assert metadata.related_documents == ["01_Other.md", "02_Other.md"]


def test_extract_metadata_falls_back_to_first_heading_when_no_frontmatter():
    content = "# Data Platform Engineering\n\nResponsibilities:\n\n- Data pipelines.\n"

    metadata = extract_metadata(content, "03_Engineering_Organization.md")

    assert metadata.title == "Data Platform Engineering"
    assert metadata.document_id is None
    assert metadata.related_documents == []


def test_extract_metadata_handles_completely_missing_metadata():
    metadata = extract_metadata("", "empty.md")

    assert metadata.title is None
    assert metadata.document_id is None
    assert metadata.related_documents == []


def test_extract_metadata_coerces_single_string_related_document():
    content = "---\ntitle: X\nrelated_documents: only_one.md\n---\n\n# X\n"

    metadata = extract_metadata(content, "x.md")

    assert metadata.related_documents == ["only_one.md"]


def test_extract_metadata_preserves_unmodeled_frontmatter_in_extra():
    content = "---\ntitle: X\neffective_date: 2026-01-15\ncustom_field: custom_value\n---\n\n# X\n"

    metadata = extract_metadata(content, "x.md")

    assert metadata.effective_date == "2026-01-15"
    assert metadata.extra == {"custom_field": "custom_value"}
