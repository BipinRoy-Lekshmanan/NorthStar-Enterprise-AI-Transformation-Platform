# app/

Application source for the Northstar Enterprise AI Transformation Platform.

## Implemented (Milestone 1)

| Module | Purpose |
|---|---|
| `config/settings.py` | `IngestionSettings.from_env()` — validated, environment-driven configuration |
| `config/logging.py` | Centralized logging setup |
| `models/document.py` | `DocumentMetadata`, `LoadedDocument`, `DocumentLoadError` (pydantic) |
| `models/chunk.py` | `Chunk` (pydantic) |
| `ingestion/document_loader.py` | `DocumentDiscoveryService` — recursive, deterministic file discovery |
| `ingestion/markdown_loader.py` | `MarkdownLoader` — safe UTF-8 loading with per-file error isolation |
| `ingestion/metadata_extractor.py` | YAML frontmatter + heading parsing |
| `ingestion/pipeline.py` | `IngestionPipeline` — wires discovery → load → chunk → persist |
| `embeddings/chunking.py` | `MarkdownChunker` — heading-aware, size/overlap-bounded chunking |

## Implemented (Milestone 2)

| Module | Purpose |
|---|---|
| `config/settings.py` | `RetrievalSettings.from_env()` — same file, same validation pattern as `IngestionSettings` |
| `models/query.py` | `RetrievalQuery` (pydantic) |
| `models/response.py` | `RetrievalResult`, `RetrievalDiagnostics`, `RetrievalResponse` (pydantic) |
| `embeddings/vectorizer.py` | `EmbeddingProvider` protocol, structured errors, `LocalHashingEmbeddingProvider` (default, offline) |
| `embeddings/openai_provider.py` | `OpenAIEmbeddingProvider` — lazy-imports `openai`, only needed when selected |
| `embeddings/vector_store.py` | `VectorStore` protocol, `LocalVectorStore` (numpy + JSON, persisted to `vector_store/`) |
| `embeddings/indexer.py` | `Indexer` — incremental sync (content-addressed `chunk_id` set-diff), CLI: `python -m app.embeddings.indexer` |
| `rag/retriever.py` | `Retriever` — embed → search → rank + diagnostics, CLI: `python -m app.rag.retriever "<question>"` |

See the [root README](../README.md) for how to run the pipeline, indexer,
retriever, and tests.

## Placeholders (future milestones)

Every other module here (`agents/`, `services/`, `api/`, `auth/`,
`cache/`, `telemetry/`, `evaluation/`, `frontend/`, `prompts/`,
`ingestion/pdf_loader.py`, `embeddings/emdedding_service.py`,
`embeddings/reranker.py`, `models/citation.py`,
`rag/generator.py`, `rag/citation_engine.py`, `rag/context_builder.py`,
`rag/hybrid_search.py`, `rag/pipeline.py`) is empty scaffolding, not yet
implemented. In particular, everything in `rag/` besides `retriever.py`
is reserved for a future milestone that adds LLM answer generation on
top of Milestone 2's retrieval — do not assume any behavior from them.
