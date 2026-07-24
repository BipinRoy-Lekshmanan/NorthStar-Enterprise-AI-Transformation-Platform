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

## Implemented (Milestone 3)

| Module | Purpose |
|---|---|
| `config/settings.py` | `RagSettings.from_env()` — same file, same pattern as Ingestion/RetrievalSettings |
| `config/prompt_config.py` | `PROMPT_VERSION`, `GROUNDING_GUARDRAILS`, grounded-RAG `SYSTEM_PROMPT`, `build_system_prompt()`, `build_prompt()` |
| `models/citation.py` | `Citation` (pydantic) |
| `models/response.py` | + `RagAnswer`, `RagDiagnostics` (alongside Milestone 2's models) |
| `services/llm_service.py` | `LanguageModelProvider` protocol, structured errors, `FakeModelProvider` (default, offline) |
| `services/openai_llm_provider.py` | `OpenAIModelProvider` — lazy-imports `openai`, only needed when selected |
| `rag/context_builder.py` | `ContextBuilder` — rank-preserving, dedup, size-bounded, decides sufficiency |
| `rag/citation_engine.py` | `parse_citation_ids()` / `build_citations()` — only ids actually cited |
| `rag/pipeline.py` | `RagService` — orchestrates the full grounded workflow, CLI: `python -m app.rag.ask "<question>"` (via `app/rag/ask.py`) |
| `evaluation/rag_evaluator.py` | Seed-dataset evaluation runner, CLI: `python -m app.rag.evaluate` (via `app/rag/evaluate.py` alias). `--category workflows` defers entirely to `evaluation/workflow_evaluator.py` (Milestone 6) so one CLI entry point reaches both evaluation datasets |
| `rag/index.py`, `rag/evaluate.py` | Thin one-line aliases for `app.embeddings.indexer.main` / `app.evaluation.rag_evaluator.main` — real logic stays in its own layer; these just give all user-facing RAG commands one namespace (`app.rag.index` / `app.rag.ask` / `app.rag.evaluate`) |

## Implemented (Milestone 4)

| Module | Purpose |
|---|---|
| `agents/base_agent.py` | `Advisor` frozen dataclass — persona + structure + extra guidance + default filters + `domain_keywords`, `ask()` delegates straight to `RagService.ask()` |
| `agents/registry.py` | `ADVISOR_REGISTRY`, `get_advisor()`, `list_advisors()`, `UnknownAdvisorError` |
| `agents/architecture_advisor.py`, `ai_engineering_advisor.py`, `devsecops_advisor.py`, `testing_advisor.py`, `release_advisor.py`, `platform_advisor.py`, `incident_advisor.py`, `developer_experience_advisor.py` | 8 advisors with a default `document_id` filter (each maps to one well-populated KB document) |
| `agents/security_advisor.py`, `ai_transformation_advisor.py` | 2 advisors with **no** default filter (cross-cutting topics spread across multiple documents) |
| `rag/ask.py` | + `--advisor <id>` / `--list-advisors` flags (same CLI, no new command) |

## Implemented (Milestone 5)

| Module | Purpose |
|---|---|
| `rag/pipeline.py` | + `RagService.llm` property (getter only, mirrors the existing `.retriever` property) |
| `config/settings.py` | + `RouterSettings.from_env()` — same file, same pattern as Ingestion/Retrieval/RagSettings |
| `config/prompt_config.py` | + `SynthesisInput`, `build_synthesis_prompt()` — reuses `GROUNDING_GUARDRAILS` for the one bounded synthesis call |
| `agents/router.py` | `RoutingDecision` frozen dataclass, `AdvisorRouter` — deterministic primary/supporting advisor selection from a retrieval signal + a keyword signal, no LLM call |
| `agents/orchestrator.py` | `ConsolidatedAdvisorResponse` frozen dataclass, `AdvisorOrchestrator` — bounded execution (primary → supporting → at most one synthesis call), citation dedup by `chunk_id`, `build_default_orchestrator()` |
| `rag/ask.py` | + `--auto-route` flag (mutually exclusive with `--advisor`) — always prints a `Routing:` block, then the consolidated answer |

## Implemented (Milestone 6)

| Module | Purpose |
|---|---|
| `models/workflow.py` | `ReviewFinding`, `EvidenceGap`, `ApprovalDecision`, `WorkflowStageResult`, `WorkflowExecution` (pydantic — persisted, unlike Milestone 5's plain-dataclass routing/orchestration types) |
| `config/settings.py` | + `WorkflowSettings.from_env()` — same file, same pattern as every other settings class |
| `config/prompt_config.py` | + `WorkflowSynthesisInput`, `build_workflow_synthesis_prompt()` — reuses `GROUNDING_GUARDRAILS` for the workflow's one bounded synthesis call |
| `workflows/definitions.py` | `WorkflowStageDefinition`, `WorkflowDefinition` frozen dataclasses, `validate_definition()` (cycle detection via Kahn's algorithm, duplicate/unsupported-type/missing-stage rejection, precomputed `execution_order`) |
| `workflows/registry.py` | `WORKFLOW_REGISTRY`, `get_workflow()`, `list_workflows()`, `UnknownWorkflowError` — static dict, eager validation at import time, same pattern as `agents/registry.py` |
| `workflows/input_validation.py` | `validate_input()` — schema-driven required-field/enum/type checks + `EvidenceGap` detection for missing-but-expected optional fields |
| `workflows/conflict_detection.py` | `detect_conflicts()` — rule-based, literal-phrase stance detection between advisor answers on the same topic; no LLM |
| `workflows/synthesis.py` | `run_synthesis_stage()`, `dedupe_citations()` — the workflow's one bounded extra LLM call, with a provider-failure fallback |
| `workflows/report.py` | `build_final_report()` — deterministic report-section assembly; the "Sources" section is always computed from citations, never from model text |
| `workflows/store.py` | `WorkflowStore` — one JSON file per execution under `workflow_store/`, atomic temp-write-then-rename, save-after-every-stage |
| `workflows/engine.py` | `WorkflowEngine` — `.run()` / `.resume()` / `.approve()` / `.cancel()`; walks the precomputed `execution_order`, dispatches by `stage_type`, persists after every stage |
| `workflows/catalog/*.py` | 5 workflow definitions: `architecture_review.py`, `ai_solution_review.py`, `production_readiness_review.py`, `incident_review.py`, `executive_ai_transformation_assessment.py` |
| `workflows/cli.py`, `workflows/__main__.py` | CLI: `python -m app.workflows list\|describe\|run\|status\|approve\|resume\|cancel` |
| `evaluation/workflow_evaluator.py` | Workflow-specific evaluation runner, CLI: `python -m app.evaluation.workflow_evaluator` |

See the [root README](../README.md) for how to run the pipeline, indexer,
retriever, RAG assistant, advisors, router, workflows, evaluators, and
tests.

## Placeholders (future milestones)

Every other module here (`api/`, `auth/`, `cache/`, `telemetry/`,
`frontend/`, `prompts/`, `ingestion/pdf_loader.py`,
`embeddings/emdedding_service.py`, `embeddings/reranker.py`,
`rag/generator.py`, `rag/hybrid_search.py`,
`services/document_service.py`, `services/embedding_service.py`,
`services/logging_service.py`, `services/vector_service.py`,
`evaluation/benchmark_runner.py`, `evaluation/llm_judge.py`,
`evaluation/retrieval_metrics.py`, `evaluation/sample_questions.py`,
`agents/business_advisor.py`, `agents/engineering_advisor.py`) is empty
scaffolding — deliberately: `business_advisor.py` isn't one of the 10
requested advisors, and `engineering_advisor.py` was superseded by the
more specific `ai_engineering_advisor.py`. Do not assume any behavior
from any of these.
