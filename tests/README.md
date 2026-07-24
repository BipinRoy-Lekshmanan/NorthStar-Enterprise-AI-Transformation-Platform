# tests/

Pytest suite for the ingestion pipeline (Milestone 1), the semantic
indexing/retrieval layer (Milestone 2), and the grounded RAG assistant
(Milestone 3).

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
| `test_llm_service.py` | `LanguageModelProvider` error hierarchy, `FakeModelProvider` determinism and citation-marker echoing |
| `test_openai_llm_provider.py` | `OpenAIModelProvider` success/timeout/rate-limit/auth/not-found/unexpected-error paths, missing-package handling, secrets-not-logged — via a fake `openai` module injected into `sys.modules` |
| `test_prompt_config.py` | Prompt version, guardrail phrases present, source-id formatting, injected text never in the system prompt |
| `test_context_builder.py` | Ranking preservation, source-id assignment, dedup, size/chunk limits, sufficiency classification |
| `test_citation_engine.py` | Valid/duplicate/invalid citation parsing, citations built only for ids actually cited |
| `test_rag_pipeline.py` | Full workflow: sufficient/insufficient context, provider failure, empty/long question, no retrieval results, diagnostics, filters |
| `test_guardrails.py` | Prompt-injection fixture (injected text stays in the user prompt, pipeline doesn't special-case it), secrets and full context text never logged at INFO, model output size bounded |

All Milestone 2 and 3 tests use `LocalHashingEmbeddingProvider` and
`FakeModelProvider` — no network calls, no API key required, same
offline-test philosophy as Milestone 1. `test_openai_llm_provider.py` is
the one exception that touches provider-specific code, and it does so
via a fake module, not the real SDK.

`pytest.ini` sets `pythonpath = .` so `import app...` resolves without an
installed package.
