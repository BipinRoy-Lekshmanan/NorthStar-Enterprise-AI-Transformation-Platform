# Roadmap

## Milestone 1 — Knowledge Ingestion Foundation ✅ Complete

Discovers Northstar Markdown documents, loads them safely, extracts
metadata, and splits them into Markdown-aware chunks with structured
output ready for a future embedding step. No LLM calls, embeddings,
vector DB, RAG, agents, or UI/API.

Delivered in `app/config`, `app/models`, `app/ingestion`,
`app/embeddings/chunking.py`. See root `README.md` for details.
Verified against the real knowledge base: 42 files, 0 errors, 820 chunks.

## Milestone 2 — Semantic Indexing & Retrieval ✅ Complete

Embeds Milestone 1 chunks, stores them in a persistent local vector
store, keeps the index in sync incrementally, and retrieves ranked
chunks + diagnostics for a question. No LLM answer generation, agents,
advisor routing, API, UI, or conversation memory.

Delivered in `app/embeddings/vectorizer.py` (+ `openai_provider.py`,
`vector_store.py`, `indexer.py`) and `app/rag/retriever.py`, plus
`RetrievalSettings` in `app/config/settings.py` and
`RetrievalQuery`/`RetrievalResponse` in `app/models/`. See root
`README.md` for details and `tests/` (69 tests total) for coverage.
Verified against the real knowledge base: 820/820 chunks indexed,
incremental re-sync reports `added=0, removed=0, unchanged=820`, and
representative Northstar questions retrieve the correct
document/section with the default local embedding provider.

## Milestone 3+ — not started

Everything else described in the platform vision (LLM answer
generation, citations, specialized engineering advisors, architecture
review support, AI governance, DevSecOps guidance, testing/release
advisors, incident response assistance, evaluation/observability,
UI/API) is still empty scaffolding under `app/` (agents/, services/,
api/, evaluation/, telemetry/, and everything in `rag/` besides
`retriever.py`). Build on top of Milestone 2's `Retriever` /
`RetrievalResponse` rather than re-implementing embedding/indexing/search.
