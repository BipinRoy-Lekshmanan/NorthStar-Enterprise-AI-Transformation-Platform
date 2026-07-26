# Decisions

## Milestone 1 — Knowledge Ingestion Foundation

- **Chunking is character-based, not token-based.** No tokenizer dependency
  was added in this milestone; `CHUNK_SIZE`/`CHUNK_OVERLAP` are character
  counts. Revisit if a future embedding step wants token-accurate sizing.
- **Chunk IDs are content-addressed**: `sha256(source_path::index::text)[:16]`.
  Editing a document changes the IDs of the chunks it touches — this is
  intentional (stable-for-identical-content, not stable-across-edits).
- **Small heading sections are merged, not dropped**, using whichever
  sub-segment contributed the most characters as the merged chunk's
  heading identity — avoids both tiny fragments and mislabeling merged
  content with an unrepresentative parent heading.
- **Table-cutting avoidance is best-effort**: chunks only get nudged past a
  Markdown table boundary within a bounded slack budget; a table larger
  than that budget can still be split.
- **Frontmatter parsing tolerates malformed/absent YAML** by falling back to
  the first Markdown heading as the document title, since several
  knowledge-base files (e.g. `03_Engineering_Organization.md`, README
  stubs) have no frontmatter at all.
- **Fixed a pre-existing bug**: several `app/` packages used `_init_.py`
  (single underscores) instead of `__init__.py`. Corrected only in the
  packages touched by Milestone 1 (`app`, `config`, `models`, `ingestion`,
  `embeddings`) — left as-is elsewhere since those packages are still
  unimplemented placeholders.
- **Repo is a standalone git repository** nested inside
  `C:\Users\bipin\projects\` (separate from whatever the parent folder
  tracks), pushed to `github.com/BipinRoy-Lekshmanan/haie-platform`
  (renamed from `NorthStar-Enterprise-AI-Transformation-Platform` when
  the project was rebranded as the HAIE Platform, keeping NorthStar
  Lending Corporation as the unchanged fictional reference enterprise).

## Milestone 2 — Semantic Indexing & Retrieval

- **Local vector store, not FAISS/Chroma**: numpy arrays + JSON metadata,
  persisted under the pre-existing (previously empty) `vector_store/`
  directory. Chosen over FAISS/ChromaDB — no new heavy dependency, and a
  linear scan is plenty fast at this KB's scale (hundreds–low thousands
  of chunks). Swappable later behind the `VectorStore` protocol.
- **Two embedding providers behind one `EmbeddingProvider` protocol**:
  `LocalHashingEmbeddingProvider` (default) is a dependency-free, offline,
  deterministic signed-feature-hashing bag-of-words embedder — chosen so
  the whole pipeline (including all tests) runs with zero API keys and
  zero network calls. `OpenAIEmbeddingProvider` is available for real
  semantic quality (`EMBEDDING_PROVIDER=openai`) and lazy-imports the
  `openai` package so it's never required for the core install.
- **Incremental indexing reuses Milestone 1's content-addressed
  `chunk_id`** instead of separate change-tracking: sync is a plain set
  diff (`current - existing` = add, `existing - current` = remove,
  intersection = skip re-embedding). An edited chunk gets a new id, so
  "update" falls out of add+remove for free.
- **Vector store validates provider/model/dimension consistency on
  reload** (`index_state.json`) and refuses to mix embeddings from a
  different provider/model into the same store — switching
  `EMBEDDING_PROVIDER` requires pointing `VECTOR_STORE_DIR` at a new
  (empty) directory rather than silently corrupting search.
- **Fixed a pre-existing bug**: `app/rag/_init_.py` (typo) → `__init__.py`,
  same pattern as Milestone 1, now that `app/rag/retriever.py` is used.
- **Windows console encoding**: the retriever CLI reconfigures stdout to
  UTF-8 with `errors="replace"` -- discovered because
  `16_Incident_Management.md` contains "✓" characters that crashed
  `print()` under the default Windows cp1252 console codepage.

## Milestone 3 — Grounded Enterprise RAG Assistant (CLI)

- **OpenAI (Chat Completions) chosen as the real LLM provider**, not
  Anthropic, per explicit user preference: it reuses the `openai`
  package already optional for Milestone 2's embedding provider, so one
  API key can unlock both embeddings and generation. Mirrors
  `openai_provider.py`'s lazy-import + error-translation pattern exactly
  (`app/services/openai_llm_provider.py`).
- **Default `LLM_PROVIDER=fake`, not `openai`** — same reasoning as
  `EMBEDDING_PROVIDER=local` in Milestone 2: the full CLI, evaluator, and
  test suite work offline with zero API keys; real grounded answers are
  one env var + one key away. `FakeModelProvider`'s answers are clearly
  labeled placeholder text, never mistaken for a real answer.
- **Insufficient-context is decided before any LLM call**, from raw
  retrieval results (no results / low top score / nothing usable after
  filtering) — `ContextBuilder.build()` computes this and `RagService`
  never builds a prompt or calls the model when it's False. This is the
  milestone's core guardrail: weak context can never be silently papered
  over by a fluent-sounding invented answer.
- **Known limitation, confirmed via `python -m app.evaluation.rag_evaluator`**:
  the default local hashing embedding provider's insufficient-context
  detection is unreliable. It's lexical/hash-based, not semantic — even
  a completely unrelated question (e.g. "Who is the CEO of Northstar in
  real life?") scores 0.30+ against `INSUFFICIENT_CONTEXT_MIN_SCORE=0.15`
  purely from shared vocabulary ("Northstar") and hash-collision noise in
  short query vectors (512 dims, few tokens). Both insufficient-context
  seed cases fail under `EMBEDDING_PROVIDER=local`; all 12 content
  questions' expected-document retrieval passed. Deliberately not
  "fixed" by tuning thresholds against a weak baseline — the milestone
  spec explicitly asked to keep the threshold logic simple, and the
  correct fix is a real embedding provider (`EMBEDDING_PROVIDER=openai`),
  not threshold-chasing. Documented in the README Limitations section.
- **Citations are reconstructed only from ids the model actually cited**,
  never all supplied sources — `citation_engine.py` intersects parsed
  `[S#]` markers against the ids present in the prompt, dropping unknown
  ids with a warning rather than accepting them.
- **Character-based context budget, not token-based** — consistent with
  Milestone 1's chunking (also character-based); documented as a known
  approximation since providers tokenize differently.
- **Provider failures and invalid questions raise rather than becoming
  disguised content** — `QuestionValidationError`/`ModelProviderError`
  propagate out of `RagService.ask()`; a `RagAnswer` always represents a
  real attempt with real grounding, never a masked error.
- **`OpenAIModelProvider` is tested via a fake `openai` module injected
  into `sys.modules`** (not by installing/calling the real SDK) — the
  `_translate_error` logic matches on exception *class name* rather than
  `isinstance`, specifically so fake exception classes with matching
  names exercise the same code path without needing the real package.
- **Fixed a pre-existing bug**: `app/services/_init_.py` (typo) →
  `__init__.py`, same pattern as Milestones 1–2, now that
  `app/services/llm_service.py` is used.

## Milestone 4 — Pluggable Advisor Framework

- **Advisors are declarative data, not subclasses.** `Advisor` is a
  single frozen dataclass (persona, structure, extra guidance, default
  filters); each of the 8 advisor modules just instantiates it. No class
  hierarchy, no per-advisor `ask()` override — `Advisor.ask()` is the
  only behavior, shared by all 8, and it does nothing but compose a
  system prompt and call `RagService.ask()`. This was the most literal
  reading of "thin specialization": if an advisor ever needs real
  behavior beyond prompt/filter composition, that's a sign it belongs in
  `RagService` itself (shared), not duplicated per advisor.
- **Two purely-additive extension points, not changes, to Milestone 1-3
  files**: `build_prompt()` and `RagService.ask()` each gained two
  optional kwargs (`system_prompt`, `prompt_version`) defaulting to
  today's behavior when omitted. Verified by re-running the entire
  Milestone 1-3 test suite unmodified (still green) and confirming
  `SYSTEM_PROMPT` is byte-identical after extracting
  `GROUNDING_GUARDRAILS` out of it (`test_generic_system_prompt_is_unchanged_by_the_advisor_refactor`).
- **6 of 8 advisors get a default `document_id` retrieval filter; 2
  deliberately don't.** Verified via `grep document_id` across
  `enterprise_knowledge_base/04_Engineering/`: Architecture (`NLC-ENG-002`),
  AI Engineering (`-003`), DevSecOps (`-004`), Testing (`-005`), Incident
  Management (`-007`), and Platform Engineering (`-008`) each map to
  exactly one well-populated source document, so a hard filter is a safe
  precision win. Security and Executive AI Transformation get **no**
  default filter: `enterprise_knowledge_base/03_Architecture/Security_Architecture.md`
  is an empty placeholder, and Northstar's real security guidance lives
  in DevSecOps Standards' + AI Engineering Standards' "AI Security
  Standards" section; similarly "AI Transformation Perspective" content
  is repeated across many documents, not concentrated in one. Confirmed
  live: asking the Security advisor about AI security controls correctly
  pulled from *both* `12_AI_Engineering_Standards.md` and
  `13_DevSecOps_Standards.md` in the same answer.
- **Caller-supplied filters always override an advisor's default on the
  same key** (`{**default_filters, **caller_filters}`) — an explicit CLI
  `--document-id` always wins over the advisor's soft default, never the
  reverse.
- **A filtered advisor whose document isn't present in the index reports
  insufficient context, not a crash or a cross-document answer** —
  discovered organically while writing the integration test fixture (a
  2-document KB with no `NLC-ENG-002` content made the Architecture
  advisor correctly report insufficient context) and kept as an explicit
  regression test rather than special-cased away.
- **No dynamic plugin discovery for the registry** — `app/agents/registry.py`
  is a hand-written static tuple. Adding a 9th advisor is "write one file
  + add one registry line," fully auditable, no import-scanning magic.
- **Advisor selection is manual only** (`--advisor <id>` on the existing
  `app.rag.ask` CLI) — no routing/classification logic decides which
  advisor answers a question. Explicitly out of scope per the milestone
  spec; `app/agents/orcherstrator.py` stays an empty placeholder for
  that future milestone.
- **Reused existing `app/agents/*_advisor.py` stub filenames where they
  matched** (architecture, ai_transformation → renamed conceptually to
  "Executive AI Transformation", platform, security) and created new
  files only where no stub fit (`ai_engineering_advisor.py`,
  `devsecops_advisor.py`, `testing_advisor.py`, `incident_advisor.py`,
  `registry.py`). `business_advisor.py` and the generic
  `engineering_advisor.py` stay empty — not among the 8 requested
  advisors.
- **Fixed a pre-existing bug**: `app/agents/_init_.py` (typo) →
  `__init__.py`, same pattern as Milestones 1–3, now that
  `app/agents/base_agent.py` is used. Left `orcherstrator.py`'s own
  filename typo alone — it's still unimplemented and out of scope.

## Milestone 5 — Advisor Router & Controlled Multi-Advisor Synthesis

- **Routing is computed from two deterministic signals, never an LLM
  call.** The milestone's hard requirement ("deterministic, explainable,
  testable, human-controlled") ruled out an LLM classification step:
  identical input must always produce identical output. Signal 1 reuses
  the exact Milestone 2 `Retriever` (one unfiltered call, scores
  attributed to whichever advisor's `default_filters["document_id"]`
  matches). Signal 2 is substring matching against a new
  `Advisor.domain_keywords` field, covering the two cross-cutting
  advisors (Security, Executive AI Transformation) that have no
  retrieval-filter signal.
- **The retrieval signal is kept on its absolute cosine-similarity
  scale, not normalized to make the top advisor "1.0".** This was a
  live bug caught during manual verification, not a design choice made
  up front: max-normalizing per-question made *every* question look
  confidently routable, because an irrelevant question's best-matching
  document is still "the best of a bad set" and normalization discarded
  how bad that set actually was (`fallback_used` never triggered even
  for "what is the best recipe for chocolate chip cookies?"). Fixed by
  averaging each advisor's matched-chunk scores without renormalizing —
  confirmed empirically that an on-topic question's best chunk scores
  meaningfully higher (~0.40) than an off-topic one's (~0.22) even under
  the lexical `local` embedding provider, which is enough separation for
  `ROUTER_MIN_CONFIDENCE=0.15` to distinguish them reliably.
- **The router always names a primary advisor, even under low
  confidence** — no sentinel "none"/"unknown" advisor id. `fallback_used`
  is a separate boolean flag on `RoutingDecision`. Simpler contract for
  `AdvisorOrchestrator` (primary is always resolvable via
  `get_advisor()`) and for the human reading CLI output, who sees both
  the best guess and an explicit low-confidence signal together.
- **Synthesis is strictly bounded**: at most one extra LLM call, only
  triggered when `RoutingDecision.supporting_advisors` is non-empty, and
  its input is *only* the already-grounded `RagAnswer.answer` text from
  the primary and supporting advisors — never raw knowledge-base
  chunks. This is what makes multi-advisor synthesis safe to add without
  violating "no autonomous/recursive/open-ended" constraints: the model
  has nothing to invent new claims from, only to consolidate what
  already-grounded advisors said. `build_synthesis_prompt()` reuses
  `GROUNDING_GUARDRAILS` via the same `build_system_prompt()` every
  advisor uses, with `extra_guidance` redirecting citation style to
  advisor-name attribution instead of `[S#]` tags (synthesis input isn't
  numbered sources).
- **Final citations are a `chunk_id`-deduped union of every advisor's own
  `Citation` objects, never re-derived from the synthesis text.** Nothing
  the synthesis step writes can fabricate a citation — the citation list
  is fully determined before the synthesis call even happens.
- **Primary-insufficient-context short-circuits before any supporting or
  synthesis call** — same "don't proceed on weak context" philosophy
  `RagService` already enforces at the single-advisor level, extended to
  the orchestrator level.
- **Added the Release and Developer Experience advisors during this
  milestone's build**, closing the gap between the 8 advisors Milestone
  4 shipped and the 10 named in the platform's advisor list (confirmed
  with the user rather than assumed): `release_advisor.py` →
  `NLC-ENG-006`, `developer_experience_advisor.py` → `NLC-ENG-009`, both
  single well-populated source documents. Retroactively documented under
  Milestone 4 in the README/roadmap since that's conceptually where they
  belong (the platform's advisor set), with a note that they were
  actually implemented during Milestone 5.
- **`RagService.llm` and `Advisor.domain_keywords` are the only two edits
  to pre-Milestone-5 files**, both purely additive (a new getter, a new
  optional dataclass field defaulting to `()`) — verified by re-running
  the entire Milestone 1-4 test suite unmodified (still green) before
  adding any Milestone 5 test.
- **Fixed a pre-existing bug**: `app/agents/orcherstrator.py` (typo,
  empty stub reserved by Milestone 4's decisions log for "a future
  milestone that adds advisor routing/orchestration") was deleted and
  replaced by `app/agents/orchestrator.py` (correct spelling), now that
  it's actually implemented.

## Milestone 6 — Enterprise Workflow Orchestration

- **Scoped to the 5 fully-specified workflows, not the 7 named in the
  objective.** Architecture Review, AI Solution Review, Production
  Readiness Review, Incident Review, and Executive AI Transformation
  Assessment each got input fields, a stage list, and report sections in
  the spec; Release Risk Review and Platform Onboarding Review were only
  named as examples ("workflows such as") with zero further detail, and
  the spec's own Completion Criteria section only requires the 5. The
  engine and registry are generic enough that either missing workflow is
  "write one more `catalog/*.py` file" later, not an engine change.
- **`ReviewFinding`/`EvidenceGap`/`ApprovalDecision`/`WorkflowStageResult`/
  `WorkflowExecution` are pydantic; `WorkflowDefinition`/`WorkflowStageDefinition`
  are frozen dataclasses.** Same split Milestone 3-5 already established
  (`Citation`/`RagAnswer` pydantic, `RoutingDecision`/`ConsolidatedAdvisorResponse`
  dataclasses): the pydantic models are what actually gets persisted
  (`WorkflowStore` writes/reads them every single stage, so
  `model_dump(mode="json")`/`model_validate()` round-tripping nested
  citations for free matters); the dataclasses are static config, never
  persisted, matching `Advisor`.
- **Conflict detection is new, rule-based, and deliberately coarse** —
  no dedicated module existed in Milestone 5 to reuse (only a prose
  instruction in `GROUNDING_GUARDRAILS` telling the LLM to mention
  conflicts). Built as literal-phrase stance matching (`POSITIVE_MARKERS`
  vs `BLOCKING_MARKERS` in a bounded window around a fixed topic
  keyword) rather than a second LLM judge, to keep it as deterministic
  and explainable as Milestone 5's router. Known consequence: it cannot
  fire under the default offline `FakeModelProvider`, whose placeholder
  text never contains the marker phrases — documented as a limitation,
  exercised directly with literal strings in
  `tests/test_workflow_conflict_detection.py` instead of via the
  evaluation dataset.
- **The workflow synthesis prompt lives in `app/config/prompt_config.py`,
  not a new prompts module under `app/workflows/`** — preserves the
  Milestone 5 decision that prompt text only lives in one file.
  `build_workflow_synthesis_prompt()` takes plain rendered-text
  parameters (via a new `WorkflowSynthesisInput` dataclass), never a
  workflow type, so the one-way `app/workflows` → `app/config` import
  direction never has to run backward, same trick `SynthesisInput` used
  to avoid a circular import back into `app/agents`.
- **`stage_type` is a closed set of exactly six values**
  (`validate_input`, `advisor_review`, `conflict_review`,
  `human_approval`, `executive_synthesis`, `final_report`), rejected at
  registry-load time if violated. Two spec-suggested stages that didn't
  cleanly map to a new type were folded into existing ones rather than
  growing the set: Incident Review's "Timeline and Evidence Review"
  became part of `validate_input`'s evidence-gap detection (timeline is
  just another schema field with an `evidence_gap` declaration), and
  "Blocking-Risk Approval Checkpoint" reused `human_approval` with a new
  `approval_condition="on_blocking_finding"` rather than inventing a
  seventh stage type.
- **Two narrow, declarative conditionals on `WorkflowStageDefinition` —
  `approval_condition` and `skip_unless_input_truthy` — instead of a
  rule engine.** The spec's pause conditions ("pause if Security or
  Release reports a blocking risk", "Security Advisor Review When
  Applicable") needed *some* conditionality, but a general expression
  language would have violated "no arbitrary rule DSL" from the same
  spec. Both are single named-field checks against already-computed
  execution state (prior blocking findings/gaps, or one input field),
  enumerable and fully unit-tested.
- **Stage execution order is computed once, at registry-build time, not
  re-sorted per run.** The 5 workflows' `depends_on` graphs are close to
  linear; a full dynamic scheduler would be over-engineering relative to
  actual need. `WorkflowEngine._advance()` just walks the precomputed
  `execution_order` and skips whatever's already in `stage_results` —
  this is also what makes "no duplicate stage execution" a structural
  guarantee rather than something to carefully avoid.
- **The engine persists after every single stage, not batched** — this
  is the actual resumability mechanism. `WorkflowStore.save()` writes to
  a temp file and renames into place (unlike `LocalVectorStore.persist()`,
  which doesn't bother, since it's called far less often) specifically
  because per-stage persistence multiplies the odds of an interrupted
  write.
- **A paused `awaiting_approval` execution cannot be resumed via
  `resume()` directly — `approve()` must be called first.** Simpler
  contract than allowing both entry points to do the same thing, and it
  makes "who unblocked this and what did they say" always traceable to
  an explicit `ApprovalDecision`, never an implicit "someone just
  re-ran it."
- **Production Readiness Review's bounded recommendation
  (`GO`/`GO_WITH_CONDITIONS`/`NO_GO`/`INSUFFICIENT_EVIDENCE`) is computed
  by a workflow-local function (`determine_recommendation()` in
  `catalog/production_readiness_review.py`), wired through a new
  optional `WorkflowDefinition.recommendation_rule` hook** — kept off
  the generic engine/report modules since only this one workflow needs a
  bounded enum; "the workflow engine must not directly contain
  advisor-specific logic" from the spec's Architecture Expectations
  ruled out hardcoding it into `engine.py` or `report.py`.
- **`report.py`'s narrative sections are a best-effort header-line split
  of the synthesis answer, with one deterministic exception.** The
  synthesis prompt asks the model to structure its answer using the
  workflow's declared section names, but nothing enforces that it does
  — under `FakeModelProvider` it never does. Rather than fail or
  fabricate missing sections, unmatched text collapses into the first
  declared section (never dropped). The "Sources" section is the one
  exception: always computed from `WorkflowExecution`'s own citations,
  never trusted to the model's text, so it's never lost to a formatting
  mismatch.
- **`app/evaluation/workflow_evaluator.py` is a new sibling file, not an
  extension of `rag_evaluator.py`** — same reasoning `app/agents/router.py`
  and `orchestrator.py` stayed separate from `app/rag/pipeline.py`:
  workflow eval cases have a fundamentally different shape (multi-stage
  expectations, ~10 new metric dimensions) that would force nullable
  fields and branching into an already-complete, tested module. The
  evaluation dataset only asserts `GO`/`INSUFFICIENT_EVIDENCE` recommendations
  and omits `expect_conflict=True` cases entirely, since both require
  conflict-detected findings that cannot occur under the offline
  `FakeModelProvider` the milestone requires ("must not call external
  APIs") — `NO_GO`/`GO_WITH_CONDITIONS` and conflict detection are
  covered directly in `tests/test_workflow_engine.py` /
  `tests/test_workflow_conflict_detection.py` instead.
- **`app/workflows/__main__.py` is a deliberate, spec-driven exception**
  to the rest of the codebase's "CLI is a flat file run via its full
  module path" convention (`python -m app.rag.ask`, not `python -m
  app.rag`) — the spec explicitly calls for `python -m app.workflows` as
  a bare package, so a `__main__.py` is required; `cli.py` still holds
  all the actual argument parsing and formatting logic, same
  logic/formatting split as `app/rag/ask.py`.

## Milestone 7 — Enterprise AI Platform (API + Web UI)

- **Reused the pre-existing empty `app/api/` and `app/frontend/`
  scaffolds** rather than inventing new top-level packages — both
  already matched FastAPI's and Streamlit's own idiomatic layouts
  (`dependencies/`, `middleware/`, `routes/`, `schemas/`;
  `assets/`, `components/`, `pages/`) and had been present, unused,
  since Milestone 1.
- **`app/api/services/` is a new, distinct layer from the pre-existing
  `app/services/`** — the latter is Milestone 3's low-level
  model/embedding-provider-adapter layer; reusing the same name for the
  new HTTP-facing facade layer would have been a false-friend
  collision. `app/api/services/` is the HTTP-layer equivalent of what
  every existing CLI already does one layer down: "argparse (or here,
  FastAPI routing) + pure formatting/validation, zero business logic."
- **Domain exceptions are mapped to HTTP status/error-code by a single
  fixed `{ExceptionClass: (status, ErrorCode)}` table, registered once
  at startup** (`app/api/errors.py`) — no route ever `try`/`except`s a
  domain exception. This mirrors `app/workflows/cli.py` letting
  `WorkflowEngineError` bubble to one top-level handler rather than
  catching per-command. Two codes needed a genuinely new API-level
  distinction the raw exception doesn't carry (`WORKFLOW_AWAITING_APPROVAL`
  vs. `WORKFLOW_ALREADY_COMPLETED` — both raised by the engine as the
  same `WorkflowEngineError`), so `app.api.services.workflow_service`/
  `approval_service` check `WorkflowExecution.status` *proactively*
  before calling the engine, instead of parsing the exception's message
  string.
- **`KeyError`-subclassing domain exceptions (`UnknownAdvisorError`,
  `UnknownWorkflowError`) needed a small `_exception_message()` helper**
  in `errors.py` — `KeyError.__str__` wraps its first arg in `repr()`,
  producing a doubled-quoted message (`"'Unknown advisor x'"`) if
  `str(exc)` were used directly; the helper reads `exc.args[0]` instead.
- **Pydantic `field_validator`s that raise `ValueError` broke JSON
  serialization of 422 responses** — `RequestValidationError.errors()`
  includes a `ctx` key holding the raw exception object, which
  `JSONResponse`'s `json.dumps` can't serialize. Fixed by stripping
  `ctx` (keeping only `type`/`loc`/`msg`/`input`) before building the
  response body, since `msg` already carries the human-readable text.
- **RBAC is four hierarchical roles backed by a local, git-ignored JSON
  file** (`data/auth/users.json`, committed template
  `users.example.json`) — explicitly not full SSO/OAuth/SAML/LDAP, per
  the milestone's own scope. `role_at_least()` plus dependency
  composition order (`get_current_user` before `require_role`) makes
  401-vs-403 fall out structurally rather than from an `if` branch.
- **`/query` is viewer-tier; `/advisors/{id}/query` is engineer-tier** —
  initially built both at engineer-tier, then corrected against the
  spec's own permission table: "ask grounded questions" (viewer) and
  "run advisor queries" (engineer) are two distinct permissions, not
  one. No user correction prompted this — caught by re-reading the
  spec's table before finalizing.
- **A FastAPI `TestClient(app)` without a `with` block never triggers
  the `lifespan`** — tests that need `app.state.X` must use `with
  TestClient(app) as client:`; tests hitting only lifespan-independent
  routes (`/health`) work either way. Discovered empirically, not
  documented clearly in FastAPI's own docs at the version pinned here.
- **Every new settings-backed singleton added to the lifespan needs its
  own tmp_path override in tests, or it silently writes into the real
  project directory** — hit twice (once for `AUDIT_LOG_DIR`, once
  pre-emptively handled for `RetrievalSettings`/the vector store) before
  becoming a standing checklist item for every subsequent singleton
  (`WorkflowSettings`, `EvaluationSettings`).
- **Route registration order matters for path collisions**:
  `GET /workflows/executions` (literal) was originally registered
  *after* `GET /workflows/{workflow_id}` (single path param) and got
  silently swallowed — Starlette matches routes in registration order,
  so `workflow_id="executions"` matched first and returned 404. Fixed
  by moving every literal-segment route ahead of same-shape
  path-param routes; caught by a genuinely failing test, not by
  inspection.
- **Knowledge document filtering re-runs `IngestionPipeline.run(persist=False)`
  fresh on every request** rather than caching, because `Chunk` (the
  vector-store-indexed model) lacks `owner`/`status`/`classification` —
  only `LoadedDocument.metadata` (from re-reading frontmatter) has them.
  The KB is small (42 files) so this is fast; a real production system
  would cache this, but that's an explicit, documented tradeoff, not an
  oversight.
- **The "document domain" filter is derived as the top-level KB folder
  name from `source_path`** (e.g. `04_Engineering`) rather than
  fabricating a `domain` field that doesn't exist anywhere in the data
  model — a real, non-invented proxy for a spec-requested filter that
  had no backing field.
- **`routing_mode` is accepted as a request field but validated to only
  ever equal `"auto"`** — the spec's example payload implied multiple
  selectable routing modes, but only one deterministic algorithm
  (Milestone 5) exists. Rejecting any other value with a clear message
  was chosen over either silently ignoring the field or fabricating
  additional modes.
- **The workflow input form is one generic, `input_schema`-driven
  component** (`app/frontend/components/forms.py`), not 5 hand-built
  forms — the real catalog only ever uses 3 field types (`string`,
  `list`, `enum`), confirmed by inspecting every workflow's
  `input_schema` before writing the renderer, so an unrecognized future
  type falls back to a plain text field rather than crashing.
- **Evaluation run persistence is a genuinely new capability, not a
  refactor** — neither `rag_evaluator.py` nor `workflow_evaluator.py`
  persisted anything before this milestone (both only printed to
  stdout); `EvaluationRunStore` mirrors `WorkflowStore`'s exact shape
  (one JSON file per run, temp-write-then-rename) rather than inventing
  a new persistence pattern.
- **Per-check pass rates in an evaluation run's `summary` are computed
  generically** from whatever keys appear in each result's `checks`
  dict, rather than hard-coding either evaluator's specific check
  names — a future evaluator adding a new check needs no change to
  `app.api.services.evaluation_service`.
- **`?format=json|markdown` on `POST /query` and the workflow-report
  endpoint, rather than separate endpoints** — same computed
  answer/report, rendered two ways; returning a `PlainTextResponse`
  directly bypasses FastAPI's `response_model` serialization cleanly
  for the markdown case. Streamlit's download buttons call the API's
  own `?format=markdown` endpoint (a second request) rather than
  importing `app.export` directly into the frontend, keeping the
  frontend a pure API client even though the export module is
  technically pure Python with no I/O — this was a deliberate
  architecture-boundary choice, not a technical necessity.
- **The rate limiter and audit log are explicitly per-process/
  in-memory-or-local-file, not distributed** — the milestone's own
  scope says "a simple in-memory rate limiter," and a shared backend
  (Redis, a database) would be premature infrastructure for a
  single-process reference deployment. Documented as a limitation, not
  silently assumed away.
- **Found via live end-to-end validation, not unit tests**: evaluation
  runs were the one significant action never audit-logged (every other
  mutating action — ingestion, indexing, rebuild, questions, workflow
  execute/resume/cancel, approval decisions — already was). The gap
  only became visible by checking the actual audit trail after
  triggering a real run against the live API, not from reading the
  code in isolation.

## Milestone 8 — Production Hardening & Operations

- **A public-vs-private cross-module helper convention was applied
  consistently**: whenever a private (`_`-prefixed) helper needed to be
  imported from a different module, it was renamed to public instead
  of importing the underscore-prefixed name across a module boundary
  (`_run_locked` → `run_locked`, `_alembic_config` → `alembic_config`,
  `_finalize_workflow_metrics` → `finalize_workflow_metrics`,
  `_parse_bool` → `parse_bool`). A leading underscore marking "private
  to this file" stops being true the moment another module imports it
  anyway; renaming makes the real contract visible instead of leaving
  a lie in the name.
- **Every new settings-backed singleton added to the API lifespan
  needs its own tmp_path override in tests, or it silently writes into
  the real project directory** — the exact same lesson from Milestone
  7, hit again for real: a 68KB `data/app.db` appeared in the repo
  after a test run because no test set `DATABASE_URL`, so
  `DatabaseSettings.from_env()` fell back to the real path. Fixed with
  an autouse `_isolated_database_url` fixture in `tests/conftest.py`
  covering every test globally, since `DATABASE_URL` is touched by
  every app-boot path, not just the tests that exercise `app.db`
  directly.
- **Alembic's `env.py` calling `fileConfig()` evicted pytest's
  `caplog` handler** — `fileConfig()` unconditionally replaces the
  root logger's handlers because `alembic.ini` declares an explicit
  `[logger_root]` section, exactly the hazard
  `app.config.logging.configure_logging()` was already written to
  avoid. Fixed by skipping `fileConfig()` when `PYTEST_CURRENT_TEST`
  is set.
- **A Zip Slip vulnerability (CWE-22) was found in `restore_backup()`
  during this milestone's own security review, before shipping** —
  `zipfile.ZipFile.extractall()` will happily write outside the
  target directory for a member name containing `../` components.
  Fixed via `_safe_extract()`, which validates every archive member's
  resolved path stays within the staging directory before extracting;
  covered by a regression test using a crafted `../../evil.txt` entry.
- **`build_engine()` didn't create a missing parent directory for a
  `sqlite:///` URL** — unlike every other Milestone 1-7 store (which
  `mkdir()`s its own directory), SQLite itself won't create one. A
  real robustness gap, found and fixed while building `app/db/`.
- **Restricted-document-filtering routes (data classification) briefly
  turned a subset of the test suite from ~40s to ~9 minutes** — new
  `get_ingestion_settings` dependencies injected into several route
  modules, but the corresponding test fixtures never overrode it, so
  `app.state.ingestion_settings` (set once at lifespan startup)
  defaulted to the real, large `enterprise_knowledge_base/`. Fixed by
  setting `KNOWLEDGE_BASE_DIRS` inside each affected test file's own
  `client` fixture, pointing at that file's own already-seeded
  tmp_path KB.
- **`APP_VERSION` staleness**: `app/api/version.py` held a version
  string one release behind `pyproject.toml`'s `[project].version`
  for an entire milestone, caught only by hand while building
  `/platform/info`. Rather than just fixing the value, this became a
  permanent automated regression guard
  (`app.release.validate._check_version_consistency()`) — the
  discipline of "found by hand once" turning into "can't silently
  recur" is the actual fix, not the one-line value correction.
- **`/health/ready` initially reached into `request.app.state`
  directly instead of using `Depends()`** — this made it impossible to
  override the RAG service via `app.dependency_overrides` in tests the
  same way every other route already supported. Caught before
  committing and refactored to `Depends(get_rag_service)`/
  `Depends(get_audit_store)`, keeping every route's testability
  convention uniform.
- **Env vars read once at API lifespan startup** (`FEATURE_FLAGS`,
  `DAILY_BUDGET_USD`, `INCLUDE_CITATION_EXCERPTS`) **can't be
  exercised through the shared `client` fixture** most route tests
  reuse, since that fixture's app instance is already built by the
  time a test's `monkeypatch.setenv()` runs. Tests that specifically
  need one of these flags build their own `create_app()` instance
  after setting the env var, reusing the same builder helper functions
  as the shared fixture rather than duplicating them.
- **`FakeModelProvider` never accrues cost** (it's absent from
  `token_usage.py`'s static pricing table by design — there's no real
  API bill to estimate) — so the budget-exceeded API test seeds usage
  directly on the real `CostTracker` singleton
  (`app.state.cost_tracker.record_usage(...)`) rather than trying to
  make a real query expensive enough to trip the budget.
- **SBOM generation shells out to `cyclonedx-py`'s own CLI against the
  installed environment**, not `requirements.txt` directly — this
  repo's `requirements.txt` is range-pinned (`fastapi>=0.110`), which
  would otherwise show up in the SBOM as "no pinned version" for every
  single package; generating from the actual installed environment
  gives every component a real exact version.
- **`deploy/k8s/04-api.yaml` runs `replicas: 1` with
  `strategy: Recreate`, not a rolling update** — SQLite and the local
  vector/workflow stores are single-writer; a second pod would briefly
  try to open the same `ReadWriteOnce` PVCs (and the same SQLite file)
  as the pod being replaced during a rolling update. Scaling past 1
  needs a real multi-writer database and shared storage first, out of
  this milestone's persistence scope — a documented constraint, not an
  oversight to fix later by just bumping a number.
- **Docker and `kubectl` are not installed in this sandbox** — every
  containerization and Kubernetes artifact (Milestone 8's `Dockerfile.
  api`/`Dockerfile.ui`/`docker-compose.yml`/`deploy/k8s/*.yaml`) could
  only be verified statically (paths exist, YAML parses, env vars
  trace correctly through `app.config.settings`) until
  `.github/workflows/ci.yml`'s `docker-build` job runs a real
  `docker build` on a GitHub Actions runner. Disclosed explicitly
  rather than claimed as verified, both in the commit messages and in
  the root README.
- **The load-test harness's `run_load_test()` takes an optional ASGI
  transport parameter** specifically so the exact same code path runs
  two ways: a real `httpx.AsyncClient` against a real socket (the CLI,
  and the one real live run performed against a real
  `python -m app.api` process) or an in-process
  `httpx.ASGITransport(app=...)` (the test suite) — avoiding a second,
  parallel "test version" of the harness that could drift from what
  actually runs in production.
- **Live end-to-end verification (not just unit tests) was run for
  7 named operational scenarios** against a real running server in an
  isolated scratch environment before considering the milestone done:
  circuit breaker trip + fail-fast, restricted-document filtering,
  rate-limit 429 + audit event, idempotency-key reuse, a real
  Prometheus metrics scrape, a live backup/restore round trip with
  hash-chain verification, and release validation in both a clean and
  an intentionally-broken simulated environment. All 7 passed with no
  code changes needed — the value was in proving the *integration*
  behavior, not just each unit in isolation.
