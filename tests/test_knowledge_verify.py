"""Tests for `app.knowledge.verify.verify_index` (Milestone 8) -- a
healthy in-sync index, missing/stale drift, and structural corruption.
Small tmp_path fixture KB + `LocalHashingEmbeddingProvider` -- never the
real (large) knowledge base or its real vector store.
"""

from app.config.settings import IngestionSettings, RetrievalSettings
from app.embeddings.indexer import Indexer, build_provider_and_store
from app.ingestion.pipeline import IngestionPipeline
from app.knowledge.verify import verify_index


def _seed_kb(kb_dir):
    kb_dir.mkdir(exist_ok=True)
    (kb_dir / "doc.md").write_text(
        "---\ndocument_id: NLC-ENG-001\ntitle: Testing Strategy\n---\n\n# Testing Strategy\n\n## Coverage\n\n"
        + ("Unit and integration test coverage is required before release. " * 15),
        encoding="utf-8",
    )
    return kb_dir


def _settings(tmp_path):
    ingestion_settings = IngestionSettings(
        knowledge_base_dirs=(_seed_kb(tmp_path / "kb"),), supported_extensions=(".md",),
        chunk_size=500, chunk_overlap=50, log_level="INFO", output_dir=tmp_path / "processed",
    )
    retrieval_settings = RetrievalSettings(
        embedding_provider="local", embedding_model="local-hashing-v1", embedding_dimensions=128,
        vector_store_dir=tmp_path / "vector_store", retrieval_top_k=10, openai_api_key=None,
    )
    return ingestion_settings, retrieval_settings


def test_verify_reports_healthy_when_index_matches_the_knowledge_base(tmp_path):
    ingestion_settings, retrieval_settings = _settings(tmp_path)
    provider, store = build_provider_and_store(retrieval_settings)
    Indexer(provider, store).index_from_pipeline(IngestionPipeline(settings=ingestion_settings))

    result = verify_index(ingestion_settings, retrieval_settings)

    assert result.healthy is True
    assert result.corrupted is False
    assert result.missing_from_index == 0
    assert result.stale_in_index == 0
    assert result.indexed_chunk_count == result.knowledge_base_chunk_count
    assert result.indexed_chunk_count > 0
    assert result.issues == []


def test_verify_reports_missing_chunks_when_the_kb_has_new_content(tmp_path):
    ingestion_settings, retrieval_settings = _settings(tmp_path)
    provider, store = build_provider_and_store(retrieval_settings)
    Indexer(provider, store).index_from_pipeline(IngestionPipeline(settings=ingestion_settings))

    # New document added to the KB after indexing -- never synced.
    (tmp_path / "kb" / "doc2.md").write_text(
        "---\ndocument_id: NLC-ENG-002\ntitle: Second Doc\n---\n\n# Second\n\n## Section\n\n"
        + ("More content requiring indexing. " * 15),
        encoding="utf-8",
    )

    result = verify_index(ingestion_settings, retrieval_settings)

    assert result.healthy is False
    assert result.corrupted is False
    assert result.missing_from_index > 0
    assert result.stale_in_index == 0
    assert any("not yet indexed" in issue for issue in result.issues)


def test_verify_reports_stale_chunks_when_indexed_content_was_removed_from_the_kb(tmp_path):
    ingestion_settings, retrieval_settings = _settings(tmp_path)
    provider, store = build_provider_and_store(retrieval_settings)
    Indexer(provider, store).index_from_pipeline(IngestionPipeline(settings=ingestion_settings))

    # Document removed from the KB after indexing -- its chunks are now stale.
    (tmp_path / "kb" / "doc.md").unlink()

    result = verify_index(ingestion_settings, retrieval_settings)

    assert result.healthy is False
    assert result.corrupted is False
    assert result.missing_from_index == 0
    assert result.stale_in_index > 0
    assert any("no longer correspond" in issue for issue in result.issues)


def test_verify_reports_corruption_for_an_incomplete_vector_store(tmp_path):
    ingestion_settings, retrieval_settings = _settings(tmp_path)
    provider, store = build_provider_and_store(retrieval_settings)
    Indexer(provider, store).index_from_pipeline(IngestionPipeline(settings=ingestion_settings))

    # Simulate a crash mid-write: delete one of the three sidecar files,
    # leaving the store directory in an inconsistent state.
    (retrieval_settings.vector_store_dir / "chunk_metadata.jsonl").unlink()

    result = verify_index(ingestion_settings, retrieval_settings)

    assert result.healthy is False
    assert result.corrupted is True
    assert result.issues  # the VectorStoreError message is surfaced


def test_verify_on_an_empty_vector_store_reports_all_missing(tmp_path):
    ingestion_settings, retrieval_settings = _settings(tmp_path)
    # Never indexed at all.

    result = verify_index(ingestion_settings, retrieval_settings)

    assert result.healthy is False
    assert result.corrupted is False
    assert result.indexed_chunk_count == 0
    assert result.missing_from_index == result.knowledge_base_chunk_count
    assert result.missing_from_index > 0
