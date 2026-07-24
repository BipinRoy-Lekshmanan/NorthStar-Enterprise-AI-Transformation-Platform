# Northstar Enterprise AI Transformation Platform

An Enterprise AI Transformation Platform being built for **Northstar Lending
Corporation** (a fictional digital lending company) on top of its Markdown
enterprise knowledge base — covering corporate strategy, business model,
architecture, and engineering standards.

The long-term platform will provide enterprise RAG, specialized engineering
advisors, architecture review support, AI governance, DevSecOps guidance,
testing/release advisors, incident response assistance, and evaluation /
observability. It is being built incrementally, milestone by milestone.

## Status

| Milestone | Scope | Status |
|---|---|---|
| **1** | Knowledge ingestion foundation | ✅ Complete |
| 2+ | Embeddings, vector store, RAG, advisors, UI/API | Not started |

## Milestone 1 — Knowledge Ingestion Foundation

A pipeline that discovers Northstar Markdown documents, loads them safely,
extracts metadata, and splits them into Markdown-aware chunks — producing
structured output ready for a future embedding/vector-store step. No LLM
calls, embeddings, vector DB, RAG, or agent logic are included yet.

```
enterprise_knowledge_base/*.md
        │
        ▼
DocumentDiscoveryService   (app/ingestion/document_loader.py)
        │  recursively finds *.md, skips hidden/generated files, deterministic order
        ▼
MarkdownLoader              (app/ingestion/markdown_loader.py)
        │  UTF-8 read, content hash, mtime, per-file error isolation
        ▼
metadata_extractor          (app/ingestion/metadata_extractor.py)
        │  YAML frontmatter + heading structure
        ▼
MarkdownChunker              (app/embeddings/chunking.py)
        │  heading-aware segmentation, small-fragment merge, size/overlap split
        ▼
IngestionPipeline            (app/ingestion/pipeline.py)
        │  orchestrates the above, persists artifacts
        ▼
data/processed/{chunks.jsonl, errors.json, summary.json}
```

### Setup

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements-dev.txt
cp .env.example .env               # adjust if needed; defaults work out of the box
```

### Run the pipeline

```bash
python -m app.ingestion.pipeline
```

This scans `enterprise_knowledge_base/` and writes chunked output to
`data/processed/` (git-ignored — regenerate locally rather than committing it).

Last verified run: **42 files discovered, 0 load errors, 820 chunks produced.**

### Run the tests

```bash
python -m pytest
```

36 tests cover configuration validation, discovery, loading, metadata
extraction, chunking, and the end-to-end pipeline.

### Configuration

All settings are environment-driven (see `.env.example`), loaded via
`app/config/settings.py::IngestionSettings.from_env()`, and validated eagerly
with clear errors on invalid/missing paths:

| Variable | Default | Meaning |
|---|---|---|
| `KNOWLEDGE_BASE_DIRS` | `enterprise_knowledge_base` | Comma-separated dirs to scan |
| `SUPPORTED_EXTENSIONS` | `.md` | Comma-separated file extensions |
| `CHUNK_SIZE` | `1500` | Max chunk length, in characters |
| `CHUNK_OVERLAP` | `200` | Overlap between split chunks, in characters |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `INGESTION_OUTPUT_DIR` | `data/processed` | Where artifacts are written |

### Chunk output shape

```json
{
  "chunk_id": "fed3614a19ef2633",
  "text": "chunk content...",
  "chunk_index": 17,
  "document_title": "Northstar Lending Corporation - Incident Management Standard",
  "document_id": "NLC-ENG-007",
  "source_file": "16_Incident_Management.md",
  "source_path": "04_Engineering/16_Incident_Management.md",
  "section_title": "10. Major Incident Management",
  "heading_path": ["10. Major Incident Management"],
  "content_hash": "610b8bc5...",
  "char_count": 462
}
```

## Project layout

```
app/
  config/       settings.py, logging.py               — Milestone 1
  models/       document.py, chunk.py (pydantic)       — Milestone 1
  ingestion/    document_loader.py, markdown_loader.py,
                metadata_extractor.py, pipeline.py      — Milestone 1
  embeddings/   chunking.py                             — Milestone 1
                (vectorizer.py, reranker.py, etc. are future-milestone placeholders)
  agents/, rag/, services/, api/, telemetry/, ...        — placeholders for later milestones
enterprise_knowledge_base/   Northstar's Markdown knowledge base (source data)
data/processed/               generated ingestion artifacts (git-ignored)
tests/                         pytest suite
```

Everything outside `config/`, `models/`, `ingestion/`, and
`embeddings/chunking.py` is intentionally still an empty placeholder —
scaffolding for milestones that haven't been built yet.
