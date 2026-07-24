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

See the [root README](../README.md) for how to run the pipeline and tests.

## Placeholders (future milestones)

Every other module here (`agents/`, `rag/`, `services/`, `api/`, `auth/`,
`cache/`, `telemetry/`, `evaluation/`, `frontend/`, `prompts/`,
`ingestion/pdf_loader.py`, `embeddings/vectorizer.py`,
`embeddings/emdedding_service.py`, `embeddings/reranker.py`,
`models/citation.py`, `models/query.py`, `models/response.py`) is empty
scaffolding, not yet implemented. Do not assume any behavior from them.
