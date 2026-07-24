from app.embeddings.chunking import MarkdownChunker
from app.models.document import DocumentMetadata, LoadedDocument


def _document(content: str, source_path="doc.md", title="Doc Title", document_id="NLC-X-001") -> LoadedDocument:
    return LoadedDocument(
        source_file=source_path,
        source_path=source_path,
        content=content,
        content_hash="hash-abc",
        metadata=DocumentMetadata(title=title, document_id=document_id),
    )


def test_short_document_becomes_a_single_chunk():
    content = "# Doc Title\n\nA short paragraph.\n"
    chunks = MarkdownChunker(chunk_size=1000, chunk_overlap=100).chunk(_document(content))

    assert len(chunks) == 1
    assert chunks[0].section_title == "Doc Title"
    assert chunks[0].heading_path == ["Doc Title"]
    assert chunks[0].document_title == "Doc Title"
    assert chunks[0].document_id == "NLC-X-001"


def test_heading_hierarchy_is_preserved():
    # Sized so each of H2/H3 individually clears the merge threshold
    # (chunk_size // 6): the small H1 intro folds into H2, but H3 stays separate.
    content = (
        "# Incident Management\n\nIntro.\n\n"
        "## Major Incident Management\n\n"
        + ("Detail about major incidents. " * 15)
        + "\n\n### War Room Operations\n\n"
        + ("Detail about war rooms. " * 15)
    )
    chunks = MarkdownChunker(chunk_size=2000, chunk_overlap=100).chunk(_document(content))

    war_room = next(c for c in chunks if c.section_title == "War Room Operations")
    assert war_room.heading_path == [
        "Incident Management",
        "Major Incident Management",
        "War Room Operations",
    ]


def test_oversized_section_is_split_with_overlap():
    paragraph = "Sentence about reliability engineering practices. " * 10 + "\n\n"
    content = "# Big Section\n\n" + paragraph * 20  # well over 1000 chars

    chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=150)
    chunks = chunker.chunk(_document(content))

    assert len(chunks) > 1
    for chunk in chunks:
        # allow some slack for boundary/table-avoidance nudging
        assert chunk.char_count <= 1300
    # overlap: the tail of one chunk should reappear near the head of the next
    assert chunks[0].text[-50:] in chunks[1].text


def test_tiny_sibling_sections_are_merged_not_left_as_fragments():
    content = (
        "# Doc\n\n"
        "## A\n\nX\n\n"
        "## B\n\nY\n\n"
        "## C\n\n" + ("Substantial content here. " * 30)
    )
    chunker = MarkdownChunker(chunk_size=2000, chunk_overlap=100, min_chunk_chars=50)
    chunks = chunker.chunk(_document(content))

    assert all(len(c.text) >= 20 for c in chunks)
    assert not any(c.text.strip() in ("X", "Y") for c in chunks)


def test_chunk_ids_are_stable_across_runs():
    content = "# Doc\n\n" + ("Repeatable content. " * 100)
    chunker = MarkdownChunker(chunk_size=800, chunk_overlap=100)

    ids_first_run = [c.chunk_id for c in chunker.chunk(_document(content))]
    ids_second_run = [c.chunk_id for c in chunker.chunk(_document(content))]

    assert ids_first_run == ids_second_run
    assert len(ids_first_run) == len(set(ids_first_run))


def test_document_without_headings_still_chunks():
    content = "Just a paragraph with no headings at all, plain prose.\n"
    chunks = MarkdownChunker(chunk_size=1000, chunk_overlap=100).chunk(_document(content))

    assert len(chunks) == 1
    assert chunks[0].heading_path == []
    assert chunks[0].section_title is None


def test_table_is_not_split_when_it_fits_in_the_slack_budget():
    table = "| Col A | Col B |\n|-------|-------|\n" + "\n".join(
        f"| row{i} | value{i} |" for i in range(30)
    )
    content = "# Doc\n\n" + ("Padding text. " * 60) + "\n\n" + table + "\n\nAfter table.\n"

    chunker = MarkdownChunker(chunk_size=900, chunk_overlap=100)
    chunks = chunker.chunk(_document(content))

    for chunk in chunks:
        lines = chunk.text.splitlines()
        table_lines = [line for line in lines if line.strip().startswith("|")]
        if table_lines:
            # every table row present in this chunk should be a contiguous block
            first_table_idx = lines.index(table_lines[0])
            contiguous = lines[first_table_idx : first_table_idx + len(table_lines)]
            assert contiguous == table_lines
