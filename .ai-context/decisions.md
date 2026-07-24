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
