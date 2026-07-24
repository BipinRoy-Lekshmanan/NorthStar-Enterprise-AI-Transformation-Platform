from app.config.settings import IngestionSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.ingestion.pipeline import IngestionPipeline
from app.models.chunk import Chunk


def _chunk(chunk_id: str, text: str, source_path: str = "doc.md") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        text=text,
        chunk_index=0,
        source_file="doc.md",
        source_path=source_path,
        content_hash="hash",
        char_count=len(text),
    )


def _indexer(tmp_path):
    provider = LocalHashingEmbeddingProvider(dimensions=32)
    store = LocalVectorStore(tmp_path / "store")
    return Indexer(provider, store), store


def test_sync_adds_new_chunks(tmp_path):
    indexer, store = _indexer(tmp_path)

    report = indexer.sync([_chunk("a", "hello world"), _chunk("b", "goodbye world")])

    assert (report.added, report.removed, report.unchanged, report.total) == (2, 0, 0, 2)
    assert store.existing_ids() == {"a", "b"}


def test_sync_second_run_with_same_chunks_is_a_no_op(tmp_path):
    indexer, _ = _indexer(tmp_path)
    chunks = [_chunk("a", "hello world"), _chunk("b", "goodbye world")]
    indexer.sync(chunks)

    report = indexer.sync(chunks)

    assert (report.added, report.removed, report.unchanged) == (0, 0, 2)


def test_sync_removes_stale_chunks(tmp_path):
    indexer, store = _indexer(tmp_path)
    indexer.sync([_chunk("a", "hello world"), _chunk("b", "goodbye world")])

    report = indexer.sync([_chunk("a", "hello world")])

    assert (report.added, report.removed, report.unchanged) == (0, 1, 1)
    assert store.existing_ids() == {"a"}


def test_edited_chunk_gets_new_content_addressed_id(tmp_path):
    """A chunk whose text changes gets a new (Milestone 1) chunk_id -- sync
    should treat that as add-new + remove-stale, not an in-place update."""
    indexer, store = _indexer(tmp_path)
    indexer.sync([_chunk("a-v1", "original text")])

    report = indexer.sync([_chunk("a-v2", "edited text")])

    assert (report.added, report.removed) == (1, 1)
    assert store.existing_ids() == {"a-v2"}


def test_sync_persists_to_disk(tmp_path):
    directory = tmp_path / "store"
    provider = LocalHashingEmbeddingProvider(dimensions=32)
    indexer = Indexer(provider, LocalVectorStore(directory))

    indexer.sync([_chunk("a", "hello world")])

    reloaded = LocalVectorStore(directory)
    assert reloaded.count() == 1


def test_index_from_pipeline_end_to_end(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "doc.md").write_text(
        "# Doc\n\n## Section\n\n" + ("Meaningful content about incidents. " * 20), encoding="utf-8"
    )
    pipeline = IngestionPipeline(
        settings=IngestionSettings(
            knowledge_base_dirs=(kb_dir,),
            supported_extensions=(".md",),
            chunk_size=500,
            chunk_overlap=50,
            log_level="INFO",
            output_dir=tmp_path / "processed",
        )
    )
    indexer, store = _indexer(tmp_path)

    report = indexer.index_from_pipeline(pipeline)

    assert report.total > 0
    assert report.added == report.total
    assert store.count() == report.total

    # running again with unchanged source content should be a no-op
    second_report = indexer.index_from_pipeline(pipeline)
    assert second_report.added == 0
    assert second_report.unchanged == report.total
