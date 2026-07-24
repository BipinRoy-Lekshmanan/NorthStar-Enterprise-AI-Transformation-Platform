# Roadmap

## Milestone 1 — Knowledge Ingestion Foundation ✅ Complete

Discovers Northstar Markdown documents, loads them safely, extracts
metadata, and splits them into Markdown-aware chunks with structured
output ready for a future embedding step. No LLM calls, embeddings,
vector DB, RAG, agents, or UI/API.

Delivered in `app/config`, `app/models`, `app/ingestion`,
`app/embeddings/chunking.py`. See root `README.md` for details and
`tests/` (36 tests) for coverage. Verified against the real knowledge
base: 42 files, 0 errors, 820 chunks.

## Milestone 2+ — not started

Everything else described in the platform vision (enterprise RAG,
specialized engineering advisors, architecture review support, AI
governance, DevSecOps guidance, testing/release advisors, incident
response assistance, evaluation/observability, UI/API) is still empty
scaffolding under `app/` (agents/, rag/, services/, api/, embeddings/
minus chunking.py, evaluation/, telemetry/, etc.). Build on top of the
Milestone 1 models (`LoadedDocument`, `Chunk`) rather than
re-implementing discovery/loading/chunking.
