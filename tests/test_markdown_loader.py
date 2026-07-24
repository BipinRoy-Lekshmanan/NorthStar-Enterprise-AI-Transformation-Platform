from app.ingestion.document_loader import DiscoveredFile
from app.ingestion.markdown_loader import MarkdownLoader
from app.models.document import DocumentLoadError, LoadedDocument


def _discovered(path, kb_root) -> DiscoveredFile:
    return DiscoveredFile(
        absolute_path=path,
        relative_path=str(path.relative_to(kb_root)).replace("\\", "/"),
        kb_root=kb_root,
    )


def test_loads_valid_markdown_with_frontmatter(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text(
        "---\ndocument_id: NLC-TEST-001\ntitle: Test Doc\n---\n\n# Test Doc\n\nBody text.\n",
        encoding="utf-8",
    )

    result = MarkdownLoader().load(_discovered(doc, tmp_path))

    assert isinstance(result, LoadedDocument)
    assert result.source_file == "doc.md"
    assert result.source_path == "doc.md"
    assert result.metadata.document_id == "NLC-TEST-001"
    assert result.metadata.title == "Test Doc"
    assert result.content_hash
    assert result.modified_time is not None


def test_missing_file_returns_load_error_not_raise(tmp_path):
    missing = tmp_path / "missing.md"

    result = MarkdownLoader().load(_discovered(missing, tmp_path))

    assert isinstance(result, DocumentLoadError)
    assert result.source_path == "missing.md"


def test_invalid_utf8_returns_load_error_not_raise(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe not valid utf-8 \x80\x81")

    result = MarkdownLoader().load(_discovered(bad, tmp_path))

    assert isinstance(result, DocumentLoadError)
    assert "utf-8" in result.error.lower()


def test_document_without_frontmatter_still_loads(tmp_path):
    doc = tmp_path / "plain.md"
    doc.write_text("# Just A Heading\n\nSome content.\n", encoding="utf-8")

    result = MarkdownLoader().load(_discovered(doc, tmp_path))

    assert isinstance(result, LoadedDocument)
    assert result.metadata.document_id is None
    assert result.metadata.title == "Just A Heading"


def test_content_hash_is_stable_for_identical_content(tmp_path):
    doc_a = tmp_path / "a.md"
    doc_b = tmp_path / "b.md"
    doc_a.write_text("# Same\n\nContent.\n", encoding="utf-8")
    doc_b.write_text("# Same\n\nContent.\n", encoding="utf-8")

    result_a = MarkdownLoader().load(_discovered(doc_a, tmp_path))
    result_b = MarkdownLoader().load(_discovered(doc_b, tmp_path))

    assert result_a.content_hash == result_b.content_hash
