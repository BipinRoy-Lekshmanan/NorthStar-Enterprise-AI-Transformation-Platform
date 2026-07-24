"""Semantic retrieval over the indexed knowledge base.

Deliberately stops at ranked chunks + diagnostics: embeds a question,
searches the vector store, and returns results with enough diagnostic
detail (scores, latencies, provider/model, index size) to manually
verify retrieval quality. No answer generation, citations, or agent
routing -- those are future-milestone concerns that will consume
`RetrievalResponse` from here.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from app.config.settings import RetrievalSettings
from app.embeddings.vector_store import VectorStore
from app.embeddings.vectorizer import EmbeddingProvider
from app.models.chunk import Chunk
from app.models.query import RetrievalQuery
from app.models.response import RetrievalDiagnostics, RetrievalResponse, RetrievalResult

logger = logging.getLogger(__name__)

# When filters are applied, over-fetch candidates from the vector store
# before filtering + trimming to top_k, so filtering doesn't silently
# starve the result set of otherwise-relevant matches.
_FILTER_OVERFETCH_MIN = 50
_FILTER_OVERFETCH_MULTIPLIER = 10


class Retriever:
    def __init__(self, provider: EmbeddingProvider, store: VectorStore):
        self._provider = provider
        self._store = store

    def retrieve(self, query: RetrievalQuery) -> RetrievalResponse:
        embed_start = time.perf_counter()
        query_vector = self._provider.embed_query(query.text)
        embed_latency_ms = (time.perf_counter() - embed_start) * 1000

        search_k = query.top_k
        if query.filters:
            search_k = min(self._store.count(), max(query.top_k * _FILTER_OVERFETCH_MULTIPLIER, _FILTER_OVERFETCH_MIN))
            search_k = search_k or query.top_k

        search_start = time.perf_counter()
        matches = self._store.search(query_vector, top_k=search_k)
        search_latency_ms = (time.perf_counter() - search_start) * 1000

        candidates_considered = len(matches)
        if query.filters:
            matches = [m for m in matches if all(m.metadata.get(k) == v for k, v in query.filters.items())]
        matches = matches[: query.top_k]

        results = [
            RetrievalResult(chunk=Chunk.model_validate(match.metadata), score=match.score, rank=rank)
            for rank, match in enumerate(matches, start=1)
        ]

        info = self._provider.info
        diagnostics = RetrievalDiagnostics(
            query_text=query.text,
            embedding_provider=info.provider,
            embedding_model=info.model,
            embedding_dimensions=info.dimensions,
            total_indexed_chunks=self._store.count(),
            top_k=query.top_k,
            candidates_considered=candidates_considered,
            embed_latency_ms=embed_latency_ms,
            search_latency_ms=search_latency_ms,
        )
        logger.info(
            "Retrieved %d result(s) for query (%.1f chars) in %.1fms embed + %.1fms search",
            len(results), len(query.text), embed_latency_ms, search_latency_ms,
        )
        return RetrievalResponse(results=results, diagnostics=diagnostics)


def _format_result(result: RetrievalResult) -> str:
    chunk = result.chunk
    heading = " > ".join(chunk.heading_path) if chunk.heading_path else "(no heading)"
    preview = " ".join(chunk.text.split())
    if len(preview) > 160:
        preview = preview[:157] + "..."
    return f"#{result.rank}  score={result.score:.4f}  {chunk.source_path}\n    {heading}\n    {preview}"


def main() -> None:
    from app.config.logging import configure_logging
    from app.embeddings.indexer import build_provider_and_store

    parser = argparse.ArgumentParser(description="Query the Northstar semantic index.")
    parser.add_argument("question", help="Question to retrieve relevant chunks for")
    parser.add_argument("--top-k", type=int, default=None, help="Override RETRIEVAL_TOP_K")
    args = parser.parse_args()

    # Knowledge-base content can contain characters (e.g. "✓") outside a
    # legacy Windows console codepage; never crash the CLI over stdout
    # encoding -- replace what can't be displayed instead.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    configure_logging()
    settings = RetrievalSettings.from_env()
    provider, store = build_provider_and_store(settings)
    retriever = Retriever(provider, store)

    query = RetrievalQuery(text=args.question, top_k=args.top_k or settings.retrieval_top_k)
    response = retriever.retrieve(query)

    print(f"\nQuery: {query.text!r}  (top_k={query.top_k})")
    print(
        f"Index: {response.diagnostics.total_indexed_chunks} chunks, "
        f"provider={response.diagnostics.embedding_provider}, model={response.diagnostics.embedding_model}"
    )
    print(
        f"Latency: embed={response.diagnostics.embed_latency_ms:.1f}ms "
        f"search={response.diagnostics.search_latency_ms:.1f}ms\n"
    )

    if not response.results:
        print("No results (is the index empty? run: python -m app.embeddings.indexer)")
        return

    for result in response.results:
        print(_format_result(result))
        print()


if __name__ == "__main__":
    main()
