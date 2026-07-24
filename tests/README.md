# tests/

Pytest suite for the ingestion pipeline (Milestone 1) and the semantic
indexing/retrieval layer (Milestone 2).

```bash
pip install -r requirements-dev.txt
python -m pytest
```

| File | Covers |
|---|---|
| `test_settings.py` | `IngestionSettings`/`RetrievalSettings` env parsing and fail-fast validation |
| `test_document_loader.py` | Recursive discovery, hidden/generated-file filtering, deterministic order, missing-directory handling |
| `test_markdown_loader.py` | UTF-8 loading, per-file error isolation, content hashing |
| `test_metadata_extractor.py` | YAML frontmatter parsing, heading extraction, missing-metadata fallbacks |
| `test_chunking.py` | Heading-hierarchy segmentation, fragment merging, size/overlap splitting, table-boundary avoidance, stable chunk IDs |
| `test_pipeline.py` | End-to-end discover → load → chunk → persist, including artifact contents |
| `test_vectorizer.py` | `LocalHashingEmbeddingProvider` determinism, dimensions, normalization, relative similarity |
| `test_vector_store.py` | Upsert/search/delete, persistence round-trip, dimension/provider mismatch errors |
| `test_indexer.py` | Incremental sync (add/remove/unchanged), edited-chunk re-id handling, end-to-end with `IngestionPipeline` |
| `test_retriever.py` | Ranking, diagnostics, `top_k`, metadata filters, empty-index behavior |

All Milestone 2 tests use `LocalHashingEmbeddingProvider` — no network
calls, no API key required, same offline-test philosophy as Milestone 1.

`pytest.ini` sets `pythonpath = .` so `import app...` resolves without an
installed package.
