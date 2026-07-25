"""Ties chunking output to the embedding provider and vector store, with
incremental sync.

Because `Chunk.chunk_id` is already content-addressed (Milestone 1: a
hash of source path, chunk index, and chunk text), keeping the index in
sync with the knowledge base reduces to a set diff -- no separate
change-tracking is needed. An unchanged chunk keeps its id and is never
re-embedded; an edited chunk gets a new id (old one removed, new one
added); a deleted document's chunk ids simply stop appearing and are
removed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config.settings import IngestionSettings, RetrievalSettings
from app.embeddings.openai_provider import OpenAIEmbeddingProvider
from app.embeddings.vector_store import LocalVectorStore, VectorStore
from app.embeddings.vectorizer import EmbeddingProvider, LocalHashingEmbeddingProvider
from app.ingestion.pipeline import IngestionPipeline
from app.models.chunk import Chunk

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexSyncReport:
    added: int
    removed: int
    unchanged: int
    total: int


class Indexer:
    def __init__(self, provider: EmbeddingProvider, store: VectorStore):
        self._provider = provider
        self._store = store

    def sync(self, chunks: list[Chunk]) -> IndexSyncReport:
        info = self._provider.info
        self._store.set_source_info(info.provider, info.model)

        current_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        current_ids = set(current_by_id)
        existing_ids = self._store.existing_ids()

        to_add_ids = current_ids - existing_ids
        to_remove_ids = existing_ids - current_ids
        unchanged_ids = current_ids & existing_ids

        if to_remove_ids:
            self._store.delete(list(to_remove_ids))

        if to_add_ids:
            to_add_chunks = [current_by_id[cid] for cid in to_add_ids]
            texts = [chunk.text for chunk in to_add_chunks]
            vectors = self._provider.embed_texts(texts)
            metadata = [chunk.model_dump(mode="json") for chunk in to_add_chunks]
            self._store.upsert([c.chunk_id for c in to_add_chunks], vectors, metadata)

        self._store.persist()

        report = IndexSyncReport(
            added=len(to_add_ids),
            removed=len(to_remove_ids),
            unchanged=len(unchanged_ids),
            total=len(current_ids),
        )
        logger.info("Index sync complete: %s", report)
        return report

    def index_from_pipeline(self, pipeline: IngestionPipeline | None = None) -> IndexSyncReport:
        """Run Milestone 1's ingestion pipeline in-process and sync its chunks.

        Reuses `IngestionPipeline` directly rather than re-parsing
        `chunks.jsonl`, so discovery/loading/chunking stays the single
        source of truth.
        """
        pipeline = pipeline or IngestionPipeline(settings=IngestionSettings.from_env())
        result = pipeline.run(persist=True)
        return self.sync(result.chunks)


def build_provider_and_store(settings: RetrievalSettings | None = None) -> tuple[EmbeddingProvider, VectorStore]:
    """Shared factory: construct the configured embedding provider + vector store.

    Used by both the indexer and the retriever CLI so provider/store
    construction lives in exactly one place.
    """
    settings = settings or RetrievalSettings.from_env()

    if settings.embedding_provider == "openai":
        assert settings.openai_api_key is not None  # enforced by RetrievalSettings.validate()
        provider: EmbeddingProvider = OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            max_concurrent_requests=settings.embedding_max_concurrent_requests,
        )
    else:
        provider = LocalHashingEmbeddingProvider(
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )

    store = LocalVectorStore(settings.vector_store_dir)
    return provider, store


def build_default_indexer(settings: RetrievalSettings | None = None) -> Indexer:
    provider, store = build_provider_and_store(settings)
    return Indexer(provider, store)


def main() -> None:
    from app.config.logging import configure_logging

    configure_logging()
    indexer = build_default_indexer()
    indexer.index_from_pipeline()


if __name__ == "__main__":
    main()
