# tests/

Pytest suite for the ingestion pipeline (Milestone 1), the semantic
indexing/retrieval layer (Milestone 2), the grounded RAG assistant
(Milestone 3), the pluggable advisor framework (Milestone 4), the
advisor router + controlled multi-advisor synthesis (Milestone 5),
enterprise workflow orchestration (Milestone 6), and the Enterprise AI
Platform API + Streamlit UI (Milestone 7).

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
| `test_workflow_definitions.py` | `validate_definition()`: valid execution-order computation, duplicate stage ids, unknown/circular `depends_on`, unsupported `stage_type`, missing required fields per stage type, bounded stage count, disabled-workflow preservation, declaration-order tie-breaking, real-registry sanity (no dup ids, exactly 5 workflows) |
| `test_workflow_input_validation.py` | Required/enum/type checks, missing-optional-field evidence-gap generation vs. no gap when present, oversized input, non-JSON-serializable input |
| `test_workflow_conflict_detection.py` | Literal-phrase positive-vs-blocking stance conflicts, agreement produces no conflict, unrelated topics produce no conflict, non-advisor/incomplete stage results ignored, matched phrases quoted in the finding, multiple topics each produce their own finding |
| `test_workflow_synthesis.py` | `build_workflow_synthesis_prompt()` section inclusion/omission, `run_synthesis_stage()` success with `FakeModelProvider`, provider-failure fallback (`failed` status, not a crash), `dedupe_citations()` order-preserving dedup |
| `test_workflow_store.py` | Save/reload round-trip, `exists()`, missing-execution error, partial (mid-execution) stage-result preservation, overwrite-on-resave, `list_execution_ids()`, corrupt-file error, auto-created store directory |
| `test_workflow_engine.py` | Deterministic stage order, required-stage failure halts, optional-stage failure continues (visible in `errors`, not swallowed), `human_approval`/`skip_unless_input_truthy` skipping, unconditional pause, approve→resume→complete with no duplicate stage execution, reject/request_changes/cancel are terminal, disabled-workflow rejection, persistence across a fresh engine instance -- all against a synthetic `WorkflowDefinition` registered via `monkeypatch.setitem` into the real registry |
| `test_workflow_approval.py` | `ApprovalDecision` validation (valid/invalid decision values, optional fields, default timestamp), `approve()` rejected on a non-awaiting execution, reviewer/comments preserved through a store round-trip |
| `test_workflow_findings.py` | `ReviewFinding` creation, invalid severity/status rejection, all valid severities/statuses accepted, blocking is explicit not inferred from severity, citations preserved through round-trip, conflict detection collapses repeated same-topic mentions into one finding |
| `test_workflow_cli.py` | Formatting helpers directly (execution summary, stages, findings, JSON rendering, report extraction) plus full `main()` invocations for `list`/`describe`/`run`/`approve`, including error paths (unknown workflow, missing input file) |
| `test_workflow_e2e.py` | One true end-to-end test per catalog workflow (all 5) against a fixture KB covering every advisor document, confirming each workflow's expected pause behavior, citation presence, and (for Production Readiness Review) the `INSUFFICIENT_EVIDENCE` recommendation |
| `test_workflow_evaluator.py` | Real dataset loads with ≥10 cases covering all 5 workflows, a case passes when expectations match, fails when a recommendation or expected stage doesn't match, `run_evaluation()`/`_rate()` aggregate correctly |
| `test_evaluate_cli.py` | `app.evaluation.rag_evaluator.main()`'s `--category` dispatch: `--category workflows` defers entirely to `app.evaluation.workflow_evaluator` and produces its output; the default (`rag`) still runs the Milestone 3 dataset unchanged |
| `test_auth.py` | `Role`/`role_at_least()`, `User`/`load_users()` (missing file, malformed JSON, invalid role, duplicate key), `ApiSettings`/`AuthSettings` env parsing and validation |
| `test_audit.py` | `AuditEvent` defaults, `AuditStore` record/list/limit/directory-creation, `record_from_context()` with/without a context |
| `test_evaluation_run_store.py` | `EvaluationRun.pass_rate`, category/status validation, `EvaluationRunStore` save/load/list round-trips, corrupt/missing-run errors |
| `test_export.py` | Envelope building for query answers and workflow reports, Markdown rendering (sections/findings/citations/disclaimer), JSON rendering round-trips |
| `test_api_foundation.py` | App metadata, `/health`, OpenAPI docs availability |
| `test_api_errors.py` | Every domain-exception → `(status, ErrorCode)` mapping, request-id/timing headers, no stack-trace leakage |
| `test_api_pagination.py` | `validate_pagination()`/`paginate_slice()` bounds |
| `test_api_auth.py` | `require_role()` unit tests, `GET /auth/me`, startup failure on a missing/malformed users file |
| `test_api_query.py` | Manual/auto query, filters, `routing_mode` validation, diagnostics, request-id correlation, audit event, `?format=markdown` |
| `test_api_advisors.py` | List/detail/route-preview/direct-query with RBAC, unknown-advisor 404 |
| `test_api_knowledge.py` | List/filter/paginate/detail/stats/search, admin-only ingest/index/rebuild, rebuild's exact-confirmation-phrase requirement |
| `test_api_workflows.py` | List/describe/examples/execute/list-executions/get/resume/cancel/report against the real `architecture_review` catalog workflow, `WORKFLOW_AWAITING_APPROVAL`/`WORKFLOW_ALREADY_COMPLETED` preconditions, `?format=markdown` |
| `test_api_approvals.py` | Pending queue, required-comment enforcement on reject/request_changes, RBAC (reviewer-only decisions), `APPROVAL_ERROR` on an already-decided execution |
| `test_api_evaluation.py` | RBAC on triggering a run, category dispatch, persistence/listing/filtering, audit event |
| `test_api_platform.py` | Detailed health (real retrieval call), administrator-only audit log view, `limit` param |
| `test_api_safety.py` | CORS headers/preflight, request-size-limit rejection, rate-limit rejection (independent per client) |
| `test_frontend_api_client.py` | Every `ApiClient` method against a monkeypatched `httpx.request` — headers, error parsing, no real network |
| `test_frontend_session.py` | `st.session_state` helpers in Streamlit's "bare mode," no running server needed |

All Milestone 2-7 tests use `LocalHashingEmbeddingProvider` and
`FakeModelProvider` — no network calls, no API key required, same
offline-test philosophy as Milestone 1. `test_openai_llm_provider.py` is
the one exception that touches provider-specific code, and it does so
via a fake module, not the real SDK. Milestone 7's API tests use
FastAPI's `TestClient` + `app.dependency_overrides` (never
monkeypatching) to inject fake-provider-backed services and tmp_path
fixture KBs/stores per test — never the real (large) knowledge base or
its real vector/workflow/audit/evaluation-run stores.

`pytest.ini` sets `pythonpath = .` so `import app...` resolves without an
installed package.
