"""Tests for Milestone 8's catalog caching in
`app.api.services.knowledge_service` -- `build_catalog()` is cached per
`IngestionSettings`, and `run_ingestion()`/`run_incremental_index()`/
`run_full_rebuild()` all explicitly invalidate the cache so a caller
never sees stale results after a mutation.
"""

from app.api.services.knowledge_service import (
    build_catalog,
    run_incremental_index,
    run_ingestion,
)
from app.config.settings import IngestionSettings, RetrievalSettings


def _ingestion_settings(tmp_path, kb_dir):
    return IngestionSettings(
        knowledge_base_dirs=(kb_dir,), supported_extensions=(".md",),
        chunk_size=500, chunk_overlap=50, log_level="INFO", output_dir=tmp_path / "processed",
    )


def _write_doc(kb_dir, filename, document_id, title):
    kb_dir.mkdir(exist_ok=True)
    (kb_dir / filename).write_text(
        f"---\ndocument_id: {document_id}\ntitle: {title}\n---\n\n# {title}\n\n## Section\n\n"
        + ("Some real content for this document. " * 15),
        encoding="utf-8",
    )


def test_repeated_calls_with_the_same_settings_return_the_same_cached_object(tmp_path):
    kb_dir = tmp_path / "kb"
    _write_doc(kb_dir, "doc1.md", "DOC-1", "Doc One")
    ingestion_settings = _ingestion_settings(tmp_path, kb_dir)

    first = build_catalog(ingestion_settings)
    second = build_catalog(ingestion_settings)

    assert first is second  # same cached list object, not just equal


def test_repeated_calls_with_an_equal_but_distinct_settings_instance_still_hit_the_cache(tmp_path):
    """IngestionSettings is a frozen dataclass -- two separately
    constructed instances with identical field values are equal/hash
    the same, so they must share one cache entry."""
    kb_dir = tmp_path / "kb"
    _write_doc(kb_dir, "doc1.md", "DOC-1", "Doc One")

    first = build_catalog(_ingestion_settings(tmp_path, kb_dir))
    second = build_catalog(_ingestion_settings(tmp_path, kb_dir))

    assert first is second


def test_ingestion_invalidates_the_cache_so_new_content_is_visible_immediately(tmp_path):
    kb_dir = tmp_path / "kb"
    _write_doc(kb_dir, "doc1.md", "DOC-1", "Doc One")
    ingestion_settings = _ingestion_settings(tmp_path, kb_dir)

    before = build_catalog(ingestion_settings)
    assert len(before) == 1

    _write_doc(kb_dir, "doc2.md", "DOC-2", "Doc Two")
    run_ingestion(ingestion_settings)

    after = build_catalog(ingestion_settings)
    assert len(after) == 2
    assert after is not before


def test_incremental_index_invalidates_the_cache(tmp_path):
    kb_dir = tmp_path / "kb"
    _write_doc(kb_dir, "doc1.md", "DOC-1", "Doc One")
    ingestion_settings = _ingestion_settings(tmp_path, kb_dir)
    retrieval_settings = RetrievalSettings(
        embedding_provider="local", embedding_model="local-hashing-v1", embedding_dimensions=128,
        vector_store_dir=tmp_path / "vector_store", retrieval_top_k=10, openai_api_key=None,
    )

    before = build_catalog(ingestion_settings)
    assert len(before) == 1

    _write_doc(kb_dir, "doc2.md", "DOC-2", "Doc Two")
    run_incremental_index(ingestion_settings, retrieval_settings)

    after = build_catalog(ingestion_settings)
    assert len(after) == 2


def test_different_knowledge_base_dirs_get_independent_cache_entries(tmp_path):
    kb_dir_a = tmp_path / "kb_a"
    kb_dir_b = tmp_path / "kb_b"
    _write_doc(kb_dir_a, "doc.md", "DOC-A", "Doc A")
    _write_doc(kb_dir_b, "doc.md", "DOC-B", "Doc B")

    catalog_a = build_catalog(_ingestion_settings(tmp_path, kb_dir_a))
    catalog_b = build_catalog(_ingestion_settings(tmp_path, kb_dir_b))

    assert catalog_a[0].document_id == "DOC-A"
    assert catalog_b[0].document_id == "DOC-B"
