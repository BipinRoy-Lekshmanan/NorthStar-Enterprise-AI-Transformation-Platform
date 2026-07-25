"""Read-only vector-index verification/recovery diagnostics (Milestone 8).

Reuses the exact same content-addressed chunk-id set-diff logic as
`app.embeddings.indexer.Indexer.sync` (a chunk's id is already a hash
of its source path, index, and text -- Milestone 1 -- so "in sync" is
just a set comparison) but never mutates the store. Structural
corruption (truncated/mismatched files) is caught by
`LocalVectorStore`'s own load-time validation, surfaced here as
`corrupted=True` rather than letting the exception propagate.

This command only diagnoses -- a caller who wants to actually fix drift
runs `POST /knowledge/index` (incremental) or `POST /operations/rebuild`
(full), not this command.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config.settings import IngestionSettings, RetrievalSettings
from app.embeddings.indexer import build_provider_and_store
from app.embeddings.vector_store import VectorStoreError
from app.ingestion.pipeline import IngestionPipeline


@dataclass(frozen=True)
class IndexVerificationResult:
    healthy: bool
    indexed_chunk_count: int
    knowledge_base_chunk_count: int
    missing_from_index: int
    stale_in_index: int
    corrupted: bool
    issues: list[str] = field(default_factory=list)


def verify_index(
    ingestion_settings: IngestionSettings | None = None, retrieval_settings: RetrievalSettings | None = None,
) -> IndexVerificationResult:
    ingestion_settings = ingestion_settings or IngestionSettings.from_env()
    retrieval_settings = retrieval_settings or RetrievalSettings.from_env()

    try:
        _provider, store = build_provider_and_store(retrieval_settings)
    except VectorStoreError as exc:
        return IndexVerificationResult(
            healthy=False, indexed_chunk_count=0, knowledge_base_chunk_count=0,
            missing_from_index=0, stale_in_index=0, corrupted=True, issues=[str(exc)],
        )

    pipeline_result = IngestionPipeline(settings=ingestion_settings).run(persist=False)
    current_ids = {chunk.chunk_id for chunk in pipeline_result.chunks}
    existing_ids = store.existing_ids()

    missing = current_ids - existing_ids
    stale = existing_ids - current_ids

    issues: list[str] = []
    if missing:
        issues.append(f"{len(missing)} knowledge-base chunk(s) are not yet indexed.")
    if stale:
        issues.append(f"{len(stale)} indexed chunk(s) no longer correspond to any current knowledge-base chunk.")

    return IndexVerificationResult(
        healthy=not missing and not stale, indexed_chunk_count=store.count(),
        knowledge_base_chunk_count=len(current_ids), missing_from_index=len(missing), stale_in_index=len(stale),
        corrupted=False, issues=issues,
    )
