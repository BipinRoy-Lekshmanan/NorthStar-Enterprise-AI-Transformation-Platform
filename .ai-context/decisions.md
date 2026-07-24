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
  tracks), pushed to `github.com/BipinRoy-Lekshmanan/NorthStar-Enterprise-AI-Transformation-Platform`.

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
