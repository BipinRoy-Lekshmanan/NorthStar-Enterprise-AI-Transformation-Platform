# tests/

Pytest suite for the ingestion pipeline (Milestone 1), the semantic
indexing/retrieval layer (Milestone 2), the grounded RAG assistant
(Milestone 3), the pluggable advisor framework (Milestone 4), and the
advisor router + controlled multi-advisor synthesis (Milestone 5).

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
| `test_cli_aliases.py` | `app.rag.index`/`app.rag.evaluate` point at the real `app.embeddings.indexer`/`app.evaluation.rag_evaluator` implementations |
| `test_advisors.py` | Shared-guardrail prompt composition, registry (10 expected ids, unknown-id error), per-advisor structural checks (persona/structure/filters/non-empty `domain_keywords`), `Advisor.ask()` filter-merging in isolation |
| `test_advisor_integration.py` | End-to-end with `FakeModelProvider`: a filtered advisor only retrieves its own document, an unfiltered advisor retrieves across documents, a filtered advisor with no matching document reports insufficient context rather than fabricating, `RagDiagnostics.prompt_version` carries the advisor tag, the plain no-advisor path is unaffected |
| `test_router.py` | `AdvisorRouter` against an isolated fixture KB + synthetic advisors: retrieval-signal document attribution, keyword-signal hits, correct primary for an obvious single-domain question with zero supporting advisors, a supporting advisor selected only for a genuinely cross-domain question, the supporting-advisor cap, `fallback_used=True` for an unrelated question, `detected_domains` independent of final selection, routing determinism |
| `test_orchestrator.py` | `AdvisorOrchestrator` with real `RagService`/`Advisor`s + `FakeModelProvider` and a stub router (isolating orchestration from routing-signal computation): single-advisor path makes zero extra LLM calls, multi-advisor path makes exactly one synthesis call, citations are a deduped union never re-derived from synthesis text, primary-insufficient-context short-circuits before any supporting/synthesis call, warnings aggregate across calls |

All Milestone 2-5 tests use `LocalHashingEmbeddingProvider` and
`FakeModelProvider` — no network calls, no API key required, same
offline-test philosophy as Milestone 1. `test_openai_llm_provider.py` is
the one exception that touches provider-specific code, and it does so
via a fake module, not the real SDK.

`pytest.ini` sets `pythonpath = .` so `import app...` resolves without an
installed package.
