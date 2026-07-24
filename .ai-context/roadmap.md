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

## Milestone 3 — Grounded Enterprise RAG Assistant (CLI) ✅ Complete

Retrieve → bounded context → prompt → LLM → parse citations → typed
`RagAnswer` + `RagDiagnostics`. Insufficient-context questions short-
circuit before any LLM call. No specialized advisors, agent routing, UI,
or autonomous actions.

Delivered in `app/services/llm_service.py` (+ `openai_llm_provider.py`),
`app/config/prompt_config.py`, `app/rag/context_builder.py`,
`app/rag/citation_engine.py`, `app/rag/pipeline.py`, `app/rag/ask.py`
(CLI), `app/evaluation/rag_evaluator.py`, plus `RagSettings` in
`app/config/settings.py` and `Citation`/`RagAnswer`/`RagDiagnostics` in
`app/models/`. See root `README.md` for details. Verified against the
real knowledge base: the CLI runs end-to-end with both the default
`fake` provider and (when configured) real OpenAI generation; 12/14 seed
evaluation cases' retrieval checks passed. **Known limitation**: the
default `local` embedding provider's insufficient-context detection is
unreliable (lexical similarity, not semantic — see
`.ai-context/decisions.md`), expected to resolve with
`EMBEDDING_PROVIDER=openai`.

## Milestone 4 — Pluggable Advisor Framework ✅ Complete

8 domain advisors (Architecture, AI Engineering, DevSecOps, Testing,
Security, Platform Engineering, Incident Management, Executive AI
Transformation) as thin, declarative specializations over the unchanged
Milestone 3 `RagService` — persona + optional default retrieval filter +
response structure + extra guidance, composed on top of shared grounding
guardrails every advisor gets automatically. No advisor routing,
multi-agent orchestration, UI, or workflow automation.

Delivered in `app/agents/base_agent.py` (`Advisor`), `registry.py`, and
8 advisor definition modules, plus two purely-additive optional kwargs
on `app.config.prompt_config.build_prompt()` and
`RagService.ask()` (`system_prompt`, `prompt_version`) — every existing
call site omits both, so Milestone 1-3 behavior is provably unchanged
(same test suite, same byte-identical generic `SYSTEM_PROMPT`). CLI
extended with `--advisor <id>` / `--list-advisors` on the existing
`app.rag.ask`. See root `README.md` for the full advisor table and
sample output. Verified against the real knowledge base: filtered
advisors (e.g. Testing) correctly scope retrieval to their document;
unfiltered advisors (Security, Executive AI Transformation) correctly
retrieve across multiple documents; the plain no-advisor CLI path is
byte-identical to Milestone 3. 182 tests total (129 unchanged + 53 new).

## Milestone 5+ — not started

Advisor routing (automatically selecting an advisor for a question),
multi-agent orchestration, a richer evaluation/observability harness
that scores advisor-specific answers, and possibly a thin API layer are
still empty scaffolding under `app/` (`agents/orcherstrator.py`, `api/`,
`telemetry/`, and everything in `rag/`/`services/`/`evaluation/` not
listed above). Build on top of Milestone 4's `Advisor`/`ADVISOR_REGISTRY`
rather than re-implementing retrieval, context construction, prompting,
or citation parsing.
