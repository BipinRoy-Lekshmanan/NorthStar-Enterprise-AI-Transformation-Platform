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
