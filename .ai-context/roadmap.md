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

10 domain advisors (Architecture, AI Engineering, DevSecOps, Testing,
Release, Platform Engineering, Incident Management, Developer
Experience, Security, Executive AI Transformation) as thin, declarative
specializations over the unchanged Milestone 3 `RagService` — persona +
optional default retrieval filter + response structure + extra guidance,
composed on top of shared grounding guardrails every advisor gets
automatically. No advisor routing, multi-agent orchestration, UI, or
workflow automation.

Delivered in `app/agents/base_agent.py` (`Advisor`), `registry.py`, and
10 advisor definition modules, plus two purely-additive optional kwargs
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
byte-identical to Milestone 3. (Release and Developer Experience were
added during Milestone 5's build to close the gap between the 8 advisors
originally implemented and the 10 named in the platform's advisor list —
see `.ai-context/decisions.md`.)

## Milestone 5 — Advisor Router & Controlled Multi-Advisor Synthesis ✅ Complete

Deterministic advisor routing (no LLM call) and bounded multi-advisor
synthesis (at most one extra LLM call, only when supporting advisors are
selected, operating strictly on already-grounded advisor answers). No
autonomous agents, recursive planning, open-ended tool use, self-directed
workflows, shell execution, production actions, or long-running agent
loops — every call sequence is fixed and bounded (at most 4 LLM calls
total: 1 primary + up to 2 supporting + 1 synthesis).

Delivered in `app/agents/router.py` (`RoutingDecision`, `AdvisorRouter`)
and `app/agents/orchestrator.py` (`ConsolidatedAdvisorResponse`,
`AdvisorOrchestrator`), plus `RouterSettings` in
`app/config/settings.py`, `SynthesisInput`/`build_synthesis_prompt()` in
`app/config/prompt_config.py`, and two purely-additive items on existing
Milestone 3/4 files: `RagService.llm` (getter, mirrors `.retriever`) and
`Advisor.domain_keywords` (optional tuple, defaults empty). CLI extended
with `--auto-route` (mutually exclusive with `--advisor`) on the
existing `app.rag.ask`. See root `README.md` for the full design and
sample output. Verified against the real knowledge base: an obvious
single-domain question routes with zero supporting advisors and no
synthesis call; a genuinely cross-domain question selects a supporting
advisor and synthesizes exactly once; an unrelated question sets
`fallback_used=True`; the manual `--advisor` path is unaffected. 214
tests total (182 unchanged + 32 new). **Known limitation carried over
from Milestone 2/3**: routing quality (the retrieval signal specifically)
inherits the default `local` embedding provider's lexical-not-semantic
limitation — mitigated for the fallback case specifically by keeping the
retrieval signal on its absolute similarity scale rather than
normalizing it away (see `.ai-context/decisions.md`).

## Milestone 6 — Enterprise Workflow Orchestration ✅ Complete

5 predefined, bounded, human-checkpointed enterprise review workflows
(Architecture Review, AI Solution Review, Production Readiness Review,
Incident Review, Executive AI Transformation Assessment), each a fixed
sequence of specific existing advisors (Milestone 4) plus new rule-based
conflict detection, evidence-gap surfacing, and one bounded synthesis
call per workflow. Controlled orchestration, not autonomous agency: no
recursive planning, no dynamic stage creation, no production actions.

Delivered in a new `app/workflows/` package (`definitions.py`,
`registry.py`, `engine.py`, `input_validation.py`,
`conflict_detection.py`, `synthesis.py`, `report.py`, `store.py`,
`cli.py`, `catalog/` with the 5 definitions), `app/models/workflow.py`
(pydantic: `ReviewFinding`, `EvidenceGap`, `ApprovalDecision`,
`WorkflowStageResult`, `WorkflowExecution`), plus two purely-additive
items: `WorkflowSettings` in `app/config/settings.py` and
`build_workflow_synthesis_prompt()` in `app/config/prompt_config.py`.
CLI: `python -m app.workflows list|describe|run|status|approve|resume|cancel`.
Execution state persists to `workflow_store/<execution_id>.json` after
every stage, making any execution resumable from a separate process
invocation, including across a crash. See root `README.md` for the full
design, CLI usage, and sample output. Verified against the real
knowledge base and via `python -m app.evaluation.workflow_evaluator`
(10/10 seed cases passing): a missing rollback plan forces
`INSUFFICIENT_EVIDENCE` even after human approval; Architecture Review/
Incident Review/Executive Assessment always pause before their final
synthesis; Production Readiness Review/AI Solution Review pause only on
a blocking finding; a cancelled execution can never be resumed. 317
tests total (214 unchanged + 103 new).

## Milestone 7 — Enterprise AI Platform (API + Web UI) ✅ Complete

A FastAPI backend and a Streamlit frontend over everything built in
Milestones 1–6 — productization, not new intelligence. No new
retrieval, prompting, routing, or workflow logic; every route and page
is a thin wrapper. Adds local hierarchical RBAC (viewer < engineer <
reviewer < administrator), an append-only audit trail, persisted
evaluation run history (new capability — neither evaluator persisted
anything before this), Markdown/JSON report export, and a simple
in-memory rate limiter + CORS restriction + request-size cap.

Delivered in new `app/auth/`, `app/audit/`, `app/export/`, `app/api/`,
and `app/frontend/` packages, plus `app/evaluation/run_models.py`/
`run_store.py` and 2 new settings classes (`ApiSettings`,
`AuthSettings`, `EvaluationSettings`) in `app/config/settings.py`. See
root `README.md` for the full architecture diagrams, API surface,
RBAC table, and end-to-end validation results. Verified against the
real knowledge base and via 6 end-to-end scenarios run live against the
running API (grounded Q&A, routing/search, KB administration, the full
workflow approval lifecycle, RBAC boundaries, evaluation + audit
correlation) — one real gap found and fixed during that pass
(evaluation runs weren't being audit-logged). 530 tests total (319
unchanged + 211 new).

**Known limitation carried over from every prior milestone**: retrieval/
routing/evaluation quality is only as good as the default `local`
lexical hashing embedding provider; expected to improve with
`EMBEDDING_PROVIDER=openai`. The rate limiter and audit log are
per-process/local-file, not shared across multiple workers or a scaled
deployment — an explicit scope limit for this milestone. Conflict
detection still requires literal marker phrases in advisor answer text
and cannot fire under the default offline `FakeModelProvider` (carried
from Milestone 6, unchanged by this milestone).

## Milestone 8+ — not started

Nothing beyond Milestone 7 has been scoped yet. Natural next
candidates (not committed): LLM-as-judge evaluation of advisor/workflow
answer *quality* (beyond the deterministic structural checks Milestones
3, 6, and 7's evaluation persistence already do); containerized/cloud
deployment (explicitly docs-only in Milestone 7's scope); a shared
rate-limit/audit backend for a horizontally-scaled deployment.
